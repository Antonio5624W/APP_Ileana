from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response, send_file
import sqlite3
import tempfile
from datetime import datetime
import os
modo_automatico = False  # False: modo manual, True: modo automático
import pdfkit
pdfkit_config = pdfkit.configuration(wkhtmltopdf="C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe")

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'

DATABASE = 'datos.db'
print(f"Base de datos en: {os.path.abspath(DATABASE)}")

parametros = {
    "humedad": None,
    "luz": None,
    "estado_bomba": None,
    "temperatura": None  # Añade la temperatura al diccionario
}

# Registrar adaptadores y convertidores para manejar datetime correctamente
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
sqlite3.register_converter("DATETIME", lambda s: datetime.fromisoformat(s.decode("utf-8")))

# Variable global para el estado de la bomba
estado_bomba = 0  # 0: apagada, 1: encendida

# Función para conectarse a la base de datos
def get_db_connection():
    conn = sqlite3.connect(
        DATABASE, 
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    conn.row_factory = sqlite3.Row
    return conn

# Inicializar la base de datos si es necesario
def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jardin_id INTEGER NOT NULL,
            fecha DATETIME NOT NULL,
            duracion INTEGER NOT NULL,
            tipo TEXT DEFAULT 'automatica',
            FOREIGN KEY (jardin_id) REFERENCES jardines(id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Ruta principal
@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']

    # Asegúrate de inicializar correctamente los parámetros
    global parametros
    if parametros is None:
        parametros = {
            "humedad": "No disponible",
            "luz": "No disponible",
            "estado_bomba": "No disponible",
            "temperatura": "No disponible"  # Inicializa la temperatura
        }
    else:
        parametros["humedad"] = parametros.get("humedad", "No disponible")
        parametros["luz"] = parametros.get("luz", "No disponible")
        parametros["estado_bomba"] = parametros.get("estado_bomba", "No disponible")
        parametros["temperatura"] = parametros.get("temperatura", "No disponible")  # Incluye la temperatura
    
    return render_template('index.html', username=username, parametros=parametros)

#Descargar PDF wkhtmltopdf
@app.route('/descargar_pdf', methods=['GET'])
def descargar_pdf():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    conn = get_db_connection()
    usuario_id = conn.execute('SELECT id FROM usuarios WHERE username = ?', (username,)).fetchone()['id']
    
    historial = conn.execute('''
        SELECT fecha, duracion, tipo 
        FROM historial 
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    ''', (usuario_id,)).fetchall()
    conn.close()

    # Renderiza el historial en formato HTML
    rendered_html = render_template('historial_pdf.html', historial=historial)

    # Crea un archivo temporal para guardar el PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        pdfkit.from_string(rendered_html, temp_pdf.name, configuration=pdfkit_config)
        temp_pdf_path = temp_pdf.name

    # Enviar el archivo PDF como descarga
    return send_file(temp_pdf_path, as_attachment=True, download_name='historial.pdf')

@app.route('/historial', methods=['GET'])
def historial():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    conn = get_db_connection()
    usuario_id = conn.execute('SELECT id FROM usuarios WHERE username = ?', (username,)).fetchone()['id']
    
    historial = conn.execute('''
        SELECT fecha, duracion, tipo 
        FROM historial 
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    ''', (usuario_id,)).fetchall()
    conn.close()

    return render_template('historial.html', historial=historial)

# Variable global para almacenar los datos recibidos del ESP32

@app.route('/actualizar_parametros', methods=['POST'])
def actualizar_parametros():
    global parametros, estado_bomba

    data = request.get_json()

    # Actualizar los parámetros globales
    parametros['humedad'] = data.get('humedad', "No disponible")
    parametros['luz'] = data.get('luz', "No disponible")
    parametros['estado_bomba'] = data.get('estado_bomba', "No disponible")
    parametros['temperatura'] = data.get('temperatura', "No disponible")
    modo_automatico = data.get('modo_automatico', False)
    riego_emergencia = data.get('riego_emergencia', False)

    # Registrar en el historial si el riego es automático o de emergencia
    conn = get_db_connection()
    try:
        if modo_automatico or riego_emergencia:
            tipo_riego = 'emergencia' if riego_emergencia else 'automatica'
            conn.execute('''
                INSERT INTO historial (usuario_id, fecha, duracion, tipo)
                VALUES (?, ?, ?, ?)
            ''', (1, datetime.now(), 0 if parametros['estado_bomba'] == 0 else 1, tipo_riego))
            conn.commit()
    except sqlite3.Error as e:
        print(f"Error al registrar riego automático/emergencia: {e}")
    finally:
        conn.close()

    print(f"Datos actualizados: {parametros}")
    return jsonify({"status": "Datos recibidos correctamente"}), 200

# Ruta para control_riego.html
@app.route('/control_riego', methods=['GET'])
def control_riego():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    conn = get_db_connection()
    usuario_id = conn.execute('SELECT id FROM usuarios WHERE username = ?', (username,)).fetchone()['id']

    historial = conn.execute('''
        SELECT fecha, duracion, tipo 
        FROM historial 
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    ''', (usuario_id,)).fetchall()
    conn.close()

    return render_template('control_riego.html', historial=historial)


# Endpoint para consultar el historial completo (JSON)
@app.route('/historial_json', methods=['GET'])
def historial_json():
    conn = get_db_connection()
    registros = conn.execute('SELECT fecha, duracion, tipo FROM historial ORDER BY fecha DESC').fetchall()
    conn.close()
    historial = [
        {"fecha": registro['fecha'], "duracion": registro['duracion'], "tipo": registro['tipo']}
        for registro in registros
    ]
    return jsonify(historial)

#Endpoint de eliminar Historial
@app.route('/eliminar_historial', methods=['POST'])
def eliminar_historial():
    if 'username' not in session:
        return redirect(url_for('login'))

    # Obtener el usuario autenticado
    username = session['username']
    conn = get_db_connection()
    usuario_id = conn.execute('SELECT id FROM usuarios WHERE username = ?', (username,)).fetchone()['id']

    # Obtener los registros seleccionados para eliminar
    registros_a_eliminar = request.form.getlist('registros')
    if registros_a_eliminar:
        try:
            conn.execute(
                'DELETE FROM historial WHERE id IN (%s) AND usuario_id = ?' %
                ','.join('?' * len(registros_a_eliminar)),
                (*registros_a_eliminar, usuario_id)
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error al eliminar registros: {e}")
        finally:
            conn.close()

    return redirect(url_for('control_riego'))

# Endpoint para obtener el historial filtrado dinámicamente (AJAX)
@app.route('/obtener_historial', methods=['GET'])
def obtener_historial():
    if 'username' not in session:
        return jsonify({"error": "No autorizado"}), 403

    username = session['username']
    conn = get_db_connection()
    usuario_id = conn.execute('SELECT id FROM usuarios WHERE username = ?', (username,)).fetchone()['id']

    historial = conn.execute('''
        SELECT id, fecha, duracion, tipo 
        FROM historial 
        WHERE usuario_id = ?
        ORDER BY fecha DESC
    ''', (usuario_id,)).fetchall()
    conn.close()

    # Renderizar solo la tabla del historial
    return render_template('tabla_historial.html', historial=historial)



# Endpoint para controlar la bomba manualmente
@app.route('/control_bomba', methods=['POST'])
def control_bomba():
    global estado_bomba, modo_automatico

    if modo_automatico:  # Verificar si el modo automático está activo
        return jsonify({"error": "La bomba está en modo automático. No puede controlarse manualmente hasta que los valores se normalicen."}), 403

    if 'username' not in session:
        return jsonify({"error": "No autorizado"}), 403

    # Obtener el usuario en sesión
    username = session['username']
    conn = get_db_connection()
    usuario_id = conn.execute('SELECT id FROM usuarios WHERE username = ?', (username,)).fetchone()['id']

    # Obtener el estado de la bomba desde la solicitud
    data = request.get_json()
    nuevo_estado = data.get('estado', 0)
    data = request.get_json()
   

    if nuevo_estado != estado_bomba:
        estado_bomba = nuevo_estado
        try:
            # Registrar el evento en la base de datos
            conn.execute('''
                INSERT INTO historial (usuario_id, fecha, duracion, tipo) 
                VALUES (?, ?, ?, ?)
            ''', (usuario_id, datetime.now(), 0 if estado_bomba == 0 else 1, 'manual'))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error al insertar en historial: {e}")
        finally:
            conn.close()
    
    return jsonify({"status": "Estado actualizado", "estado_bomba": estado_bomba})

@app.route('/actualizar_modo_automatico', methods=['POST'])
def actualizar_modo_automatico():
    global modo_automatico
    data = request.get_json()

    # Actualizar el modo automático basado en los datos recibidos del ESP32
    modo_automatico = data.get('modo_automatico', False)
    return jsonify({"status": "Modo automático actualizado", "modo_automatico": modo_automatico}), 200

# Endpoint para consultar el estado actual de la bomba
@app.route('/bomba_estado', methods=['GET'])
def bomba_estado():
    return jsonify({"estado_bomba": estado_bomba})

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM usuarios WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if not user:  # El usuario no existe
            return render_template('login.html', error="El usuario no está registrado. Por favor, crea una cuenta.")
        
        if user['password'] != password:  # Contraseña incorrecta
            return render_template('login.html', error="Contraseña incorrecta. Inténtalo de nuevo.")
        
        # Si el usuario existe y la contraseña es correcta
        session['username'] = username
        return redirect(url_for('index'))
    return render_template('login.html')


# Logout
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# Registro
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO usuarios (username, password) VALUES (?, ?)', (username, password))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "El usuario ya está registrado. <a href='/register'>Intentar de nuevo</a>"
    return render_template('register.html')



# Historial de riego (versión JSON)
#@app.route('/historial/<int:jardin_id>', methods=['GET'])
#def historial(jardin_id):
 #   conn = get_db_connection()
  #  historial = conn.execute('SELECT fecha, duracion, tipo FROM historial WHERE jardin_id = ?', (jardin_id,)).fetchall()
   # conn.close()

    #return render_template('historial.html', historial=historial, jardin_id=jardin_id)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
