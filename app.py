import os
import time
import random
import sqlite3
import datetime
import secrets
import threading
import smtplib
import schedule
import qrcode
import pandas as pd
from email.mime.text import MIMEText
from werkzeug.utils import secure_filename

from flask import Flask, render_template, request, redirect, url_for, flash, g, send_from_directory
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, DateField, IntegerField, SelectField, FileField
from wtforms.validators import DataRequired, Length, EqualTo, Email
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

# Configuración de la aplicación
app = Flask(__name__)
app.secret_key = "una_clave_secreta_muy_segura"  # Cambia esto en producción
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit para archivos
app.config['UPLOAD_FOLDER'] = 'uploads'

# Crear directorio de uploads si no existe
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Configuración de Flask-Login
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# Directorio para códigos QR (dentro de static)
QR_DIR = os.path.join("static", "qr_codes")
if not os.path.exists(QR_DIR):
    os.makedirs(QR_DIR)

# ========================================================
# Funciones de Base de Datos y creación de tablas
# ========================================================
def get_db_connection():
    conn = sqlite3.connect("archivo.db")
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Tabla de usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE,
            reset_token TEXT,
            token_expiry TIMESTAMP
        )
    """)
    # Tabla de departamentos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS departamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cover_template TEXT
        )
    """)
    # Tabla de tipos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL
        )
    """)
    # Tabla de bodegas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bodegas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL
        )
    """)
    # Tabla de ubicaciones (con tamaño)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ubicaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tamano TEXT
        )
    """)
    # Tabla de cajas con los nuevos campos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cajas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_caja TEXT,
            departamento_id INTEGER,
            años TEXT,
            tipo_id INTEGER,
            observacion TEXT COLLATE NOCASE, 
            descripcion TEXT COLLATE NOCASE, 
            bodega_id INTEGER,
            ubicacion_id INTEGER,
            percha TEXT,
            fila TEXT,
            columna TEXT,
            qr_path TEXT,
            FOREIGN KEY(departamento_id) REFERENCES departamentos(id),
            FOREIGN KEY(tipo_id) REFERENCES tipos(id),
            FOREIGN KEY(bodega_id) REFERENCES bodegas(id),
            FOREIGN KEY(ubicacion_id) REFERENCES ubicaciones(id)
        )
    """)
    # Tabla de préstamos (sin cambios)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prestamos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caja_id INTEGER,
            item TEXT,
            loan_date TEXT,
            due_date TEXT,
            returned INTEGER DEFAULT 0,
            email TEXT,
            FOREIGN KEY(caja_id) REFERENCES cajas(id)
        )
    """)
    conn.commit()
    conn.close()

create_tables()

# ========================================================
# Modelo de Usuario para Flask-Login
# ========================================================
class User(UserMixin):
    def __init__(self, id, username, password, email=None, reset_token=None, token_expiry=None):
        self.id = id
        self.username = username
        self.password = password
        self.email = email
        self.reset_token = reset_token
        self.token_expiry = token_expiry

def get_user_by_id(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not user:
        return None
    return User(user["id"], user["username"], user["password"], 
               user["email"] if "email" in user.keys() else None,
               user["reset_token"] if "reset_token" in user.keys() else None,
               user["token_expiry"] if "token_expiry" in user.keys() else None)

def get_user_by_username(username):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not user:
        return None
    return User(user["id"], user["username"], user["password"], 
               user["email"] if "email" in user.keys() else None,
               user["reset_token"] if "reset_token" in user.keys() else None,
               user["token_expiry"] if "token_expiry" in user.keys() else None)

def update_user_password(user_id, new_password):
    conn = get_db_connection()
    hashed_password = generate_password_hash(new_password)
    conn.execute("UPDATE users SET password = ?, reset_token = NULL, token_expiry = NULL WHERE id = ?", (hashed_password, user_id))
    conn.commit()
    conn.close()

def update_user_email(user_id, email):
    conn = get_db_connection()
    conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
    conn.commit()
    conn.close()

def get_user_by_email(email):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if not user:
        return None
    return User(user["id"], user["username"], user["password"], 
               user["email"] if "email" in user.keys() else None,
               user["reset_token"] if "reset_token" in user.keys() else None,
               user["token_expiry"] if "token_expiry" in user.keys() else None)

def get_user_by_reset_token(token):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE reset_token = ?", (token,)).fetchone()
    conn.close()
    if not user:
        return None
    return User(user["id"], user["username"], user["password"], 
               user["email"] if "email" in user.keys() else None,
               user["reset_token"] if "reset_token" in user.keys() else None,
               user["token_expiry"] if "token_expiry" in user.keys() else None)

def generate_reset_token(user_id):
    token = secrets.token_urlsafe(32)
    expiry = datetime.datetime.now() + datetime.timedelta(hours=24)
    conn = get_db_connection()
    conn.execute("UPDATE users SET reset_token = ?, token_expiry = ? WHERE id = ?", 
                (token, expiry.isoformat(), user_id))
    conn.commit()
    conn.close()
    return token

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)

# ========================================================
# Formularios con Flask-WTF
# ========================================================
class LoginForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField("Contraseña", validators=[DataRequired()])
    submit = SubmitField("Ingresar")

class RegistrationForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirmar Contraseña", validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField("Registrarse")

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Contraseña Actual", validators=[DataRequired()])
    new_password = PasswordField("Nueva Contraseña", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirmar Nueva Contraseña", validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField("Cambiar Contraseña")

class UpdateEmailForm(FlaskForm):
    email = StringField("Correo Electrónico", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña Actual", validators=[DataRequired()])
    submit = SubmitField("Actualizar Correo")

class ForgotPasswordForm(FlaskForm):
    email = StringField("Correo Electrónico", validators=[DataRequired(), Email()])
    submit = SubmitField("Enviar Enlace de Recuperación")

class ResetPasswordForm(FlaskForm):
    password = PasswordField("Nueva Contraseña", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirmar Nueva Contraseña", validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField("Restablecer Contraseña")

# Nuevo formulario para cajas con los nuevos campos
class CajaForm(FlaskForm):
    departamento = SelectField("Departamento", choices=[], coerce=int, validators=[DataRequired()])
    años = StringField("Años", validators=[DataRequired()])
    tipo = SelectField("Tipo", choices=[], coerce=int, validators=[DataRequired()])
    observacion = TextAreaField("Observación")
    descripcion = TextAreaField("Descripción detallada")
    bodega = SelectField("Bodega", choices=[], coerce=int, validators=[DataRequired()])
    ubicacion = SelectField("Ubicación", choices=[], coerce=int, validators=[DataRequired()])
    percha = StringField("Percha", validators=[DataRequired()])
    fila = StringField("Fila", validators=[DataRequired()])
    columna = StringField("Columna", validators=[DataRequired()])
    submit = SubmitField("Guardar Caja")

class PrestamoForm(FlaskForm):
    caja_id = IntegerField("ID de la Caja", validators=[DataRequired()])
    item = StringField("Item (carpeta, expediente, etc.)", validators=[DataRequired()])
    loan_date = DateField("Fecha de Préstamo", format='%Y-%m-%d', validators=[DataRequired()])
    due_date = DateField("Fecha Límite de Devolución", format='%Y-%m-%d', validators=[DataRequired()])
    email = StringField("Correo del Responsable", validators=[DataRequired(), Email()])
    submit = SubmitField("Guardar Préstamo")

# Formulario para cargar archivo Excel
class ExcelUploadForm(FlaskForm):
    archivo = FileField('Archivo Excel', validators=[DataRequired()])
    submit = SubmitField('Cargar Archivo')
    
    def __init__(self, *args, **kwargs):
        super(ExcelUploadForm, self).__init__(*args, **kwargs)
        self.archivo.description = "El archivo debe incluir las columnas: id_caja (opcional), Departamento, Años, Tipo, Observacion (opcional), Descripcion (opcional), Bodega, Ubicacion, Percha, Fila, Columna"

# Formularios para los nuevos catálogos
class DepartamentoForm(FlaskForm):
    nombre = StringField("Nombre del Departamento", validators=[DataRequired()])
    submit = SubmitField("Guardar Departamento")

class TipoForm(FlaskForm):
    nombre = StringField("Nombre del Tipo", validators=[DataRequired()])
    submit = SubmitField("Guardar Tipo")

class BodegaForm(FlaskForm):
    nombre = StringField("Nombre de la Bodega", validators=[DataRequired()])
    submit = SubmitField("Guardar Bodega")

class UbicacionForm(FlaskForm):
    nombre = StringField("Nombre de la Ubicación", validators=[DataRequired()])
    tamano = StringField("Tamaño (en metros)", validators=[DataRequired()])
    submit = SubmitField("Guardar Ubicación")

# ========================================================
# Funciones para manejo de catálogos y cajas
# ========================================================

def procesar_excel_cajas(archivo_path):
    """Procesa un archivo Excel para importar cajas a la base de datos.
    El archivo debe tener las siguientes columnas:
    - id_caja (opcional, si no se proporciona se generará automáticamente)
    - Departamento (nombre del departamento)
    - Años
    - Tipo (nombre del tipo)
    - Observacion (opcional)
    - Descripcion (opcional)
    - Bodega (nombre de la bodega)
    - Ubicacion (nombre de la ubicación)
    - Percha
    - Fila
    - Columna
    """
    try:
        # Leer el archivo Excel
        df = pd.read_excel(archivo_path)
        
        # Verificar columnas requeridas
        columnas_requeridas = ['Departamento', 'Años', 'Tipo', 'Bodega', 'Ubicacion', 'Percha', 'Fila', 'Columna']
        columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]
        
        if columnas_faltantes:
            return False, f"Faltan columnas requeridas: {', '.join(columnas_faltantes)}"
        
        # Obtener mapeo de nombres a IDs
        conn = get_db_connection()
        departamentos = {d['nombre']: d['id'] for d in conn.execute("SELECT id, nombre FROM departamentos").fetchall()}
        tipos = {t['nombre']: t['id'] for t in conn.execute("SELECT id, nombre FROM tipos").fetchall()}
        bodegas = {b['nombre']: b['id'] for b in conn.execute("SELECT id, nombre FROM bodegas").fetchall()}
        ubicaciones = {u['nombre']: u['id'] for u in conn.execute("SELECT id, nombre FROM ubicaciones").fetchall()}
        
        # Verificar IDs de cajas existentes
        cajas_existentes = {c['id_caja'] for c in conn.execute("SELECT id_caja FROM cajas").fetchall()}
        conn.close()
        
        # Procesar cada fila
        cajas_agregadas = 0
        errores = []
        
        for i, row in df.iterrows():
            try:
                # Verificar si existen los catálogos
                if row['Departamento'] not in departamentos:
                    errores.append(f"Fila {i+2}: Departamento '{row['Departamento']}' no existe")
                    continue
                    
                if row['Tipo'] not in tipos:
                    errores.append(f"Fila {i+2}: Tipo '{row['Tipo']}' no existe")
                    continue
                    
                if row['Bodega'] not in bodegas:
                    errores.append(f"Fila {i+2}: Bodega '{row['Bodega']}' no existe")
                    continue
                    
                if row['Ubicacion'] not in ubicaciones:
                    errores.append(f"Fila {i+2}: Ubicación '{row['Ubicacion']}' no existe")
                    continue
                
                # Obtener valores
                departamento_id = departamentos[row['Departamento']]
                años = str(row['Años'])
                tipo_id = tipos[row['Tipo']]
                observacion = str(row.get('Observacion', '')) if not pd.isna(row.get('Observacion', '')) else ''
                descripcion = str(row.get('Descripcion', '')) if not pd.isna(row.get('Descripcion', '')) else ''
                bodega_id = bodegas[row['Bodega']]
                ubicacion_id = ubicaciones[row['Ubicacion']]
                percha = str(row['Percha'])
                fila = str(row['Fila'])
                columna = str(row['Columna'])
                
                # Verificar si se proporciona id_caja
                if 'id_caja' in df.columns and not pd.isna(row['id_caja']):
                    id_caja = str(row['id_caja'])
                    
                    # Verificar si ya existe
                    if id_caja in cajas_existentes:
                        errores.append(f"Fila {i+2}: El ID de caja '{id_caja}' ya existe en la base de datos")
                        continue
                    
                    # Agregar caja con id_caja específico
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    qr_filename = os.path.join(QR_DIR, f"{id_caja}.png")
                    generate_qr_code(id_caja, qr_filename)
                    cursor.execute(
                        "INSERT INTO cajas (id_caja, departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna, qr_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (id_caja, departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna, qr_filename)
                    )
                    conn.commit()
                    conn.close()
                    
                    # Actualizar conjunto de IDs existentes
                    cajas_existentes.add(id_caja)
                else:
                    # Usar la función existente para generar id_caja automáticamente
                    add_caja(departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna)
                
                cajas_agregadas += 1
                
            except Exception as e:
                errores.append(f"Error en fila {i+2}: {str(e)}")
        
        # Preparar mensaje de resultado
        mensaje = f"Se importaron {cajas_agregadas} cajas correctamente."
        if errores:
            mensaje += f" Hubo {len(errores)} errores: {'; '.join(errores[:5])}"
            if len(errores) > 5:
                mensaje += f" y {len(errores) - 5} más."
        
        return True, mensaje
        
    except Exception as e:
        return False, f"Error al procesar el archivo: {str(e)}"
def generate_qr_code(data, filename):
    img = qrcode.make(data)
    img.save(filename)

def get_next_id_caja():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(id_caja) FROM cajas")
    max_id = cursor.fetchone()[0]
    conn.close()
    next_id = 1 if max_id is None else int(max_id) + 1
    return str(next_id).zfill(4)

def add_caja(departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna):
    conn = get_db_connection()
    cursor = conn.cursor()
    id_caja = get_next_id_caja()
    qr_filename = os.path.join(QR_DIR, f"{id_caja}.png")
    generate_qr_code(id_caja, qr_filename)
    cursor.execute(
       "INSERT INTO cajas (id_caja, departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna, qr_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
       (id_caja, departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna, qr_filename)
    )
    conn.commit()
    conn.close()
    return id_caja

def update_caja(caja_id, departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE cajas SET departamento_id = ?, años = ?, tipo_id = ?, observacion = ?, descripcion = ?, bodega_id = ?, ubicacion_id = ?, percha = ?, fila = ?, columna = ? WHERE id = ?",
        (departamento_id, años, tipo_id, observacion, descripcion, bodega_id, ubicacion_id, percha, fila, columna, caja_id)
    )
    conn.commit()
    conn.close()

def delete_caja(caja_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM prestamos WHERE caja_id = ?", (caja_id,))
    cursor.execute("DELETE FROM cajas WHERE id = ?", (caja_id,))
    conn.commit()
    conn.close()

def get_caja_by_id(caja_id):
    conn = get_db_connection()
    caja = conn.execute("""
        SELECT cajas.*, departamentos.nombre AS departamento, tipos.nombre AS tipo, 
               bodegas.nombre AS bodega, ubicaciones.nombre AS ubicacion
        FROM cajas
        LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id
        LEFT JOIN tipos ON cajas.tipo_id = tipos.id
        LEFT JOIN bodegas ON cajas.bodega_id = bodegas.id
        LEFT JOIN ubicaciones ON cajas.ubicacion_id = ubicaciones.id
        WHERE cajas.id = ?
    """, (caja_id,)).fetchone()
    conn.close()
    return caja

def search_cajas(search_term):
    conn = get_db_connection()
    cursor = conn.cursor()
    pattern = f"%{search_term}%"
    cursor.execute("""
        SELECT cajas.*, departamentos.nombre AS departamento, tipos.nombre AS tipo, 
               bodegas.nombre AS bodega, ubicaciones.nombre AS ubicacion
        FROM cajas
        LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id
        LEFT JOIN tipos ON cajas.tipo_id = tipos.id
        LEFT JOIN bodegas ON cajas.bodega_id = bodegas.id
        LEFT JOIN ubicaciones ON cajas.ubicacion_id = ubicaciones.id
        WHERE id_caja LIKE ? 
        OR percha LIKE ? 
        OR fila LIKE ? 
        OR columna LIKE ? 
        OR años LIKE ? 
        OR departamentos.nombre LIKE ? 
        OR tipos.nombre LIKE ? 
        OR bodegas.nombre LIKE ? 
        OR ubicaciones.nombre LIKE ? 
        OR observacion LIKE ? 
        OR descripcion LIKE ?
    """, (pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern))
    results = cursor.fetchall()
    conn.close()
    return results

def get_all_cajas():
    conn = get_db_connection()
    cajas = conn.execute("""
        SELECT cajas.*, departamentos.nombre AS departamento, tipos.nombre AS tipo, 
               bodegas.nombre AS bodega, ubicaciones.nombre AS ubicacion
        FROM cajas
        LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id
        LEFT JOIN tipos ON cajas.tipo_id = tipos.id
        LEFT JOIN bodegas ON cajas.bodega_id = bodegas.id
        LEFT JOIN ubicaciones ON cajas.ubicacion_id = ubicaciones.id
    """).fetchall()
    conn.close()
    return cajas

def add_prestamo(caja_id, item, loan_date, due_date, email):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO prestamos (caja_id, item, loan_date, due_date, email) VALUES (?, ?, ?, ?, ?)",
        (caja_id, item, loan_date, due_date, email)
    )
    conn.commit()
    conn.close()

def update_prestamo(prestamo_id, caja_id, item, loan_date, due_date, email, returned):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prestamos SET caja_id = ?, item = ?, loan_date = ?, due_date = ?, email = ?, returned = ? WHERE id = ?",
        (caja_id, item, loan_date, due_date, email, returned, prestamo_id)
    )
    conn.commit()
    conn.close()

def delete_prestamo(prestamo_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM prestamos WHERE id = ?", (prestamo_id,))
    conn.commit()
    conn.close()

def get_prestamo_by_id(prestamo_id):
    conn = get_db_connection()
    prestamo = conn.execute("SELECT * FROM prestamos WHERE id = ?", (prestamo_id,)).fetchone()
    conn.close()
    return prestamo

def get_all_prestamos():
    conn = get_db_connection()
    prestamos = conn.execute("SELECT * FROM prestamos").fetchall()
    conn.close()
    return prestamos

# Funciones para obtener datos de catálogos
def get_departamentos():
    conn = get_db_connection()
    deps = conn.execute("SELECT * FROM departamentos").fetchall()
    conn.close()
    return deps

def get_tipos():
    conn = get_db_connection()
    ts = conn.execute("SELECT * FROM tipos").fetchall()
    conn.close()
    return ts

def get_bodegas():
    conn = get_db_connection()
    bds = conn.execute("SELECT * FROM bodegas").fetchall()
    conn.close()
    return bds

def get_ubicaciones():
    conn = get_db_connection()
    ubs = conn.execute("SELECT * FROM ubicaciones").fetchall()
    conn.close()
    return ubs

# ========================================================
# Funciones para notificaciones y scheduler (sin cambios)
# ========================================================
def check_overdue_loans():
    today = datetime.date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT prestamos.id, prestamos.email, cajas.id_caja, prestamos.due_date 
        FROM prestamos 
        JOIN cajas ON prestamos.caja_id = cajas.id 
        WHERE prestamos.returned = 0 AND prestamos.due_date < ?
    """, (today,))
    overdue = cursor.fetchall()
    conn.close()
    return overdue

def send_email(recipient, subject, message):
    smtp_server = "smtp.example.com"   # Configura tu servidor SMTP
    smtp_port = 587
    smtp_user = "tu_email@example.com"
    smtp_password = "tu_password"
    
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = recipient
    
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print("Correo enviado a", recipient)
    except Exception as e:
        print("Error al enviar correo:", e)

def notify_overdue_loans():
    overdue_loans = check_overdue_loans()
    for loan in overdue_loans:
        loan_id, email, id_caja, due_date = loan
        subject = f"Préstamo vencido: Caja {id_caja}"
        message = (f"El préstamo de la caja {id_caja} venció el {due_date}.\n"
                   "Por favor, gestionar la devolución a la brevedad.")
        send_email(email, subject, message)

def start_notification_scheduler():
    schedule.every().day.at("09:00").do(notify_overdue_loans)
    print("Scheduler de notificaciones iniciado...")
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_scheduler_thread():
    scheduler_thread = threading.Thread(target=start_notification_scheduler, daemon=True)
    scheduler_thread.start()

# ========================================================
# Rutas de Autenticación
# ========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = get_user_by_username(form.username.data)
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            flash("Bienvenido, " + user.username)
            return redirect(url_for("index"))
        else:
            flash("Usuario o contraseña incorrectos.")
    return render_template("login.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Has cerrado sesión correctamente.")
    return redirect(url_for("login"))

@app.route("/update_email", methods=["GET", "POST"])
@login_required
def update_email():
    form = UpdateEmailForm()
    if form.validate_on_submit():
        if check_password_hash(current_user.password, form.password.data):
            # Verificar si el correo ya está en uso
            existing_user = get_user_by_email(form.email.data)
            if existing_user and existing_user.id != current_user.id:
                flash("Este correo electrónico ya está registrado.")
                return render_template("update_email.html", form=form)
            
            update_user_email(current_user.id, form.email.data)
            flash("Correo electrónico actualizado correctamente.")
            return redirect(url_for("index"))
        else:
            flash("Contraseña incorrecta.")
    return render_template("update_email.html", form=form)

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = get_user_by_email(form.email.data)
        if user:
            token = generate_reset_token(user.id)
            reset_url = url_for("reset_password", token=token, _external=True)
            
            # Enviar correo con el enlace de recuperación
            subject = "Recuperación de contraseña - GuaziniBox"
            message = f"""Hola {user.username},

Has solicitado restablecer tu contraseña. Por favor, haz clic en el siguiente enlace para crear una nueva contraseña:

{reset_url}

Este enlace expirará en 24 horas.

Si no solicitaste este cambio, puedes ignorar este mensaje.

Saludos,
Equipo de GuaziniBox"""
            
            try:
                send_email(user.email, subject, message)
                flash("Se ha enviado un enlace de recuperación a tu correo electrónico.")
            except Exception as e:
                flash(f"Error al enviar el correo: {str(e)}")
        else:
            # Por seguridad, no revelamos si el correo existe o no
            flash("Si el correo está registrado, recibirás un enlace de recuperación.")
        
        return redirect(url_for("login"))
    
    return render_template("forgot_password.html", form=form)

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    
    user = get_user_by_reset_token(token)
    if not user:
        flash("El enlace de recuperación es inválido o ha expirado.")
        return redirect(url_for("login"))
    
    # Verificar si el token ha expirado
    if user.token_expiry:
        expiry = datetime.datetime.fromisoformat(user.token_expiry)
        if datetime.datetime.now() > expiry:
            flash("El enlace de recuperación ha expirado.")
            return redirect(url_for("login"))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        update_user_password(user.id, form.password.data)
        flash("Tu contraseña ha sido actualizada. Ahora puedes iniciar sesión.")
        return redirect(url_for("login"))
    
    return render_template("reset_password.html", form=form)

@app.route("/cambiar-clave", methods=["GET", "POST"])
@login_required
def cambiar_clave():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        user = get_user_by_id(current_user.id)
        # Verificar que la contraseña actual sea correcta
        if check_password_hash(user.password, form.current_password.data):
            # Actualizar la contraseña
            update_user_password(user.id, form.new_password.data)
            flash("Tu contraseña ha sido actualizada correctamente", "success")
            return redirect(url_for("index"))
        else:
            flash("La contraseña actual es incorrecta", "danger")
    return render_template("cambiar_clave.html", form=form)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        if get_user_by_username(form.username.data):
            flash("El usuario ya existe.")
        else:
            hashed_password = generate_password_hash(form.password.data)
            conn = get_db_connection()
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", 
                         (form.username.data, hashed_password))
            conn.commit()
            conn.close()
            flash("Registro exitoso. Ahora puedes iniciar sesión.")
            return redirect(url_for("login"))
    return render_template("register.html", form=form)

# ========================================================
# Rutas Principales (Protegidas)
# ========================================================

@app.route('/cargar_excel', methods=['GET', 'POST'])
@login_required
def cargar_excel():
    form = ExcelUploadForm()
    
    if form.validate_on_submit():
        # Guardar el archivo
        archivo = form.archivo.data
        filename = secure_filename(archivo.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        archivo.save(file_path)
        
        # Procesar el archivo
        exito, mensaje = procesar_excel_cajas(file_path)
        
        # Eliminar el archivo después de procesarlo
        if os.path.exists(file_path):
            os.remove(file_path)
        
        if exito:
            flash(mensaje, 'success')
        else:
            flash(mensaje, 'danger')
            
        return redirect(url_for('cajas'))
    
    return render_template('cargar_excel.html', form=form)
@app.route("/")
@login_required
def index():
    return render_template("index.html", user=current_user)

# Gestión de Cajas
@app.route("/cajas")
@login_required
def cajas():
    cajas = get_all_cajas()
    return render_template("cajas.html", cajas=cajas)

@app.route("/add_caja", methods=["GET", "POST"])
@login_required
def add_caja_route():
    form = CajaForm()
    form.departamento.choices = [(d["id"], d["nombre"]) for d in get_departamentos()]
    form.tipo.choices = [(t["id"], t["nombre"]) for t in get_tipos()]
    form.bodega.choices = [(b["id"], b["nombre"]) for b in get_bodegas()]
    form.ubicacion.choices = [(u["id"], u["nombre"]) for u in get_ubicaciones()]
    if form.validate_on_submit():
        id_caja = add_caja(form.departamento.data, form.años.data, form.tipo.data, form.observacion.data,
                           form.descripcion.data, form.bodega.data, form.ubicacion.data, form.percha.data, form.fila.data, form.columna.data)
        flash(f"Caja agregada con número secuencial: {id_caja}")
        return redirect(url_for("cajas"))
    return render_template("add_caja.html", form=form)

@app.route("/edit_caja/<int:caja_id>", methods=["GET", "POST"])
@login_required
def edit_caja(caja_id):
    caja = get_caja_by_id(caja_id)
    if not caja:
        flash("Caja no encontrada.")
        return redirect(url_for("cajas"))
    form = CajaForm()
    form.departamento.choices = [(d["id"], d["nombre"]) for d in get_departamentos()]
    form.tipo.choices = [(t["id"], t["nombre"]) for t in get_tipos()]
    form.bodega.choices = [(b["id"], b["nombre"]) for b in get_bodegas()]
    form.ubicacion.choices = [(u["id"], u["nombre"]) for u in get_ubicaciones()]
    if request.method == "GET":
        form.departamento.data = caja["departamento_id"]
        form.años.data = caja["años"]
        form.tipo.data = caja["tipo_id"]
        form.observacion.data = caja["observacion"]
        form.descripcion.data = caja["descripcion"] if "descripcion" in caja.keys() else ""
        form.bodega.data = caja["bodega_id"]
        form.ubicacion.data = caja["ubicacion_id"]
        form.percha.data = caja["percha"]
        form.fila.data = caja["fila"]
        form.columna.data = caja["columna"]
    if form.validate_on_submit():
        update_caja(caja_id, form.departamento.data, form.años.data, form.tipo.data, form.observacion.data,
                    form.descripcion.data, form.bodega.data, form.ubicacion.data, form.percha.data, form.fila.data, form.columna.data)
        flash("Caja actualizada exitosamente.")
        return redirect(url_for("cajas"))
    return render_template("edit_caja.html", form=form, caja=caja)

@app.route("/delete_caja/<int:caja_id>", methods=["POST"])
@login_required
def delete_caja_route(caja_id):
    delete_caja(caja_id)
    flash("Caja eliminada exitosamente.")
    return redirect(url_for("cajas"))

@app.route("/search_caja", methods=["GET"])
@login_required
def search_caja():
    query = request.args.get("query", "")
    cajas_result = None
    if query:
        cajas_result = search_cajas(query)
    return render_template("search_caja.html", cajas=cajas_result, query=query)

# Gestión de Préstamos (sin cambios significativos)
@app.route("/prestamos")
@login_required
def prestamos():
    prestamos = get_all_prestamos()
    return render_template("prestamos.html", prestamos=prestamos)

@app.route("/add_prestamo", methods=["GET", "POST"])
@login_required
def add_prestamo_route():
    form = PrestamoForm()
    if form.validate_on_submit():
        add_prestamo(form.caja_id.data, form.item.data, form.loan_date.data.isoformat(), 
                     form.due_date.data.isoformat(), form.email.data)
        flash("Préstamo registrado exitosamente.")
        return redirect(url_for("prestamos"))
    return render_template("add_prestamo.html", form=form)

@app.route("/edit_prestamo/<int:prestamo_id>", methods=["GET", "POST"])
@login_required
def edit_prestamo(prestamo_id):
    prestamo = get_prestamo_by_id(prestamo_id)
    if not prestamo:
        flash("Préstamo no encontrado.")
        return redirect(url_for("prestamos"))
    form = PrestamoForm()
    if request.method == "GET":
        form.caja_id.data = prestamo["caja_id"]
        form.item.data = prestamo["item"]
        form.loan_date.data = datetime.datetime.strptime(prestamo["loan_date"], "%Y-%m-%d").date()
        form.due_date.data = datetime.datetime.strptime(prestamo["due_date"], "%Y-%m-%d").date()
        form.email.data = prestamo["email"]
    if form.validate_on_submit():
        returned = prestamo["returned"]
        update_prestamo(prestamo_id, form.caja_id.data, form.item.data, 
                        form.loan_date.data.isoformat(), form.due_date.data.isoformat(), 
                        form.email.data, returned)
        flash("Préstamo actualizado exitosamente.")
        return redirect(url_for("prestamos"))
    return render_template("edit_prestamo.html", form=form, prestamo=prestamo)

@app.route("/delete_prestamo/<int:prestamo_id>", methods=["POST"])
@login_required
def delete_prestamo_route(prestamo_id):
    delete_prestamo(prestamo_id)
    flash("Préstamo eliminado exitosamente.")
    return redirect(url_for("prestamos"))

# CRUD de Departamentos
@app.route("/departamentos")
@login_required
def departamentos():
    deps = get_departamentos()
    return render_template("departamentos.html", departamentos=deps)

@app.route("/add_departamento", methods=["GET", "POST"])
@login_required
def add_departamento():
    form = DepartamentoForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("INSERT INTO departamentos (nombre) VALUES (?)", (form.nombre.data,))
        conn.commit()
        conn.close()
        flash("Departamento agregado.")
        return redirect(url_for("departamentos"))
    return render_template("add_departamento.html", form=form)

@app.route("/edit_departamento/<int:dep_id>", methods=["GET", "POST"])
@login_required
def edit_departamento(dep_id):
    conn = get_db_connection()
    dep = conn.execute("SELECT * FROM departamentos WHERE id = ?", (dep_id,)).fetchone()
    conn.close()
    if not dep:
        flash("Departamento no encontrado.")
        return redirect(url_for("departamentos"))
    form = DepartamentoForm()
    if request.method == "GET":
        form.nombre.data = dep["nombre"]
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("UPDATE departamentos SET nombre = ? WHERE id = ?", (form.nombre.data, dep_id))
        conn.commit()
        conn.close()
        flash("Departamento actualizado.")
        return redirect(url_for("departamentos"))
    return render_template("edit_departamento.html", form=form, departamento=dep)

@app.route("/delete_departamento/<int:dep_id>", methods=["POST"])
@login_required
def delete_departamento(dep_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM departamentos WHERE id = ?", (dep_id,))
    conn.commit()
    conn.close()
    flash("Departamento eliminado.")
    return redirect(url_for("departamentos"))

# CRUD de Tipos
@app.route("/tipos")
@login_required
def tipos():
    ts = get_tipos()
    return render_template("tipos.html", tipos=ts)

@app.route("/add_tipo", methods=["GET", "POST"])
@login_required
def add_tipo():
    form = TipoForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("INSERT INTO tipos (nombre) VALUES (?)", (form.nombre.data,))
        conn.commit()
        conn.close()
        flash("Tipo agregado.")
        return redirect(url_for("tipos"))
    return render_template("add_tipo.html", form=form)

@app.route("/edit_tipo/<int:tipo_id>", methods=["GET", "POST"])
@login_required
def edit_tipo(tipo_id):
    conn = get_db_connection()
    t = conn.execute("SELECT * FROM tipos WHERE id = ?", (tipo_id,)).fetchone()
    conn.close()
    if not t:
        flash("Tipo no encontrado.")
        return redirect(url_for("tipos"))
    form = TipoForm()
    if request.method == "GET":
        form.nombre.data = t["nombre"]
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("UPDATE tipos SET nombre = ? WHERE id = ?", (form.nombre.data, tipo_id))
        conn.commit()
        conn.close()
        flash("Tipo actualizado.")
        return redirect(url_for("tipos"))
    return render_template("edit_tipo.html", form=form, tipo=t)

@app.route("/delete_tipo/<int:tipo_id>", methods=["POST"])
@login_required
def delete_tipo(tipo_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM tipos WHERE id = ?", (tipo_id,))
    conn.commit()
    conn.close()
    flash("Tipo eliminado.")
    return redirect(url_for("tipos"))

# CRUD de Bodegas
@app.route("/bodegas")
@login_required
def bodegas():
    bds = get_bodegas()
    return render_template("bodegas.html", bodegas=bds)

@app.route("/add_bodega", methods=["GET", "POST"])
@login_required
def add_bodega():
    form = BodegaForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("INSERT INTO bodegas (nombre) VALUES (?)", (form.nombre.data,))
        conn.commit()
        conn.close()
        flash("Bodega agregada.")
        return redirect(url_for("bodegas"))
    return render_template("add_bodega.html", form=form)

@app.route("/edit_bodega/<int:bodega_id>", methods=["GET", "POST"])
@login_required
def edit_bodega(bodega_id):
    conn = get_db_connection()
    bd = conn.execute("SELECT * FROM bodegas WHERE id = ?", (bodega_id,)).fetchone()
    conn.close()
    if not bd:
        flash("Bodega no encontrada.")
        return redirect(url_for("bodegas"))
    form = BodegaForm()
    if request.method == "GET":
        form.nombre.data = bd["nombre"]
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("UPDATE bodegas SET nombre = ? WHERE id = ?", (form.nombre.data, bodega_id))
        conn.commit()
        conn.close()
        flash("Bodega actualizada.")
        return redirect(url_for("bodegas"))
    return render_template("edit_bodega.html", form=form, bodega=bd)

@app.route("/delete_bodega/<int:bodega_id>", methods=["POST"])
@login_required
def delete_bodega(bodega_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM bodegas WHERE id = ?", (bodega_id,))
    conn.commit()
    conn.close()
    flash("Bodega eliminada.")
    return redirect(url_for("bodegas"))

# CRUD de Ubicaciones
@app.route("/ubicaciones")
@login_required
def ubicaciones():
    ubs = get_ubicaciones()
    return render_template("ubicaciones.html", ubicaciones=ubs)

@app.route("/add_ubicacion", methods=["GET", "POST"])
@login_required
def add_ubicacion():
    form = UbicacionForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("INSERT INTO ubicaciones (nombre, tamano) VALUES (?, ?)", (form.nombre.data, form.tamano.data))
        conn.commit()
        conn.close()
        flash("Ubicación agregada.")
        return redirect(url_for("ubicaciones"))
    return render_template("add_ubicacion.html", form=form)

@app.route("/edit_ubicacion/<int:ubicacion_id>", methods=["GET", "POST"])
@login_required
def edit_ubicacion(ubicacion_id):
    conn = get_db_connection()
    ub = conn.execute("SELECT * FROM ubicaciones WHERE id = ?", (ubicacion_id,)).fetchone()
    conn.close()
    if not ub:
        flash("Ubicación no encontrada.")
        return redirect(url_for("ubicaciones"))
    form = UbicacionForm()
    if request.method == "GET":
        form.nombre.data = ub["nombre"]
        form.tamano.data = ub["tamano"]
    if form.validate_on_submit():
        conn = get_db_connection()
        conn.execute("UPDATE ubicaciones SET nombre = ?, tamano = ? WHERE id = ?", (form.nombre.data, form.tamano.data, ubicacion_id))
        conn.commit()
        conn.close()
        flash("Ubicación actualizada.")
        return redirect(url_for("ubicaciones"))
    return render_template("edit_ubicacion.html", form=form, ubicacion=ub)

@app.route("/delete_ubicacion/<int:ubicacion_id>", methods=["POST"])
@login_required
def delete_ubicacion(ubicacion_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM ubicaciones WHERE id = ?", (ubicacion_id,))
    conn.commit()
    conn.close()
    flash("Ubicación eliminada.")
    return redirect(url_for("ubicaciones"))

@app.route("/print_qr", methods=["GET", "POST"])
@login_required
def print_qr():
    if request.method == "POST":
        start_range = request.form.get("start_range")
        end_range = request.form.get("end_range")
        try:
            # Convertir a enteros para realizar la comparación correctamente.
            start_val = int(start_range)
            end_val = int(end_range)
        except ValueError:
            flash("Los rangos deben ser numéricos, por ejemplo: 0001.")
            return redirect(url_for("print_qr"))
        conn = get_db_connection()
        # Se hace CAST(id_caja AS INTEGER) para comparar numéricamente,
        # ya que id_caja se guarda como texto con relleno de ceros.
        cajas = conn.execute(
            "SELECT cajas.*, departamentos.nombre AS departamento, tipos.nombre AS tipo "
            "FROM cajas "
            "LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id "
            "LEFT JOIN tipos ON cajas.tipo_id = tipos.id "
            "WHERE CAST(id_caja AS INTEGER) BETWEEN ? AND ? "
            "ORDER BY CAST(id_caja AS INTEGER) ASC",
            (start_val, end_val)
        ).fetchall()
        conn.close()
        return render_template("print_qr.html", cajas=cajas, start_range=start_range, end_range=end_range)
    # GET: Mostrar formulario para ingresar el rango.
    return render_template("print_qr_form.html")


@app.route("/cover/<int:caja_id>")
@login_required
def cover_caja(caja_id):
    # 1. Obtener datos de la caja desde la base de datos
    conn = get_db_connection()
    caja = conn.execute("""
        SELECT cajas.*,
               departamentos.nombre AS departamento,
               tipos.nombre AS tipo,
               bodegas.nombre AS bodega,
               ubicaciones.nombre AS ubicacion
        FROM cajas
        LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id
        LEFT JOIN tipos         ON cajas.tipo_id         = tipos.id
        LEFT JOIN bodegas       ON cajas.bodega_id       = bodegas.id
        LEFT JOIN ubicaciones   ON cajas.ubicacion_id    = ubicaciones.id
        WHERE cajas.id = ?
    """, (caja_id,)).fetchone()
    conn.close()

    if not caja:
        flash("Caja no encontrada.")
        return redirect(url_for("cajas"))

    # 2. Determinar la plantilla en base al nombre del departamento
    #    - Reemplaza espacios por "_" y convierte a minúsculas para que coincida con tu archivo en cover/
    dept_name = (caja["departamento"] or "default").lower().replace(" ", "_")
    template_name = f"{dept_name}.html"  # Por ejemplo: "legal.html", "archivo_general.html", etc.

    # 3. Renderizar la plantilla
    try:
        return render_template(f"cover/{template_name}", caja=caja)
    except TemplateNotFound:
        # Si no existe la plantilla específica, usamos la 'default.html'
        return render_template("cover/default.html", caja=caja)

@app.route("/cover/department/<int:dep_id>")
@login_required
def cover_department(dep_id):
    conn = get_db_connection()
    # Buscar todas las cajas de ese departamento
    cajas = conn.execute("""
        SELECT cajas.*,
               departamentos.nombre AS departamento,
               tipos.nombre AS tipo,
               bodegas.nombre AS bodega,
               ubicaciones.nombre AS ubicacion
        FROM cajas
        LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id
        LEFT JOIN tipos         ON cajas.tipo_id         = tipos.id
        LEFT JOIN bodegas       ON cajas.bodega_id       = bodegas.id
        LEFT JOIN ubicaciones   ON cajas.ubicacion_id    = ubicaciones.id
        WHERE departamentos.id = ?
        ORDER BY CAST(cajas.id_caja AS INTEGER) ASC
    """, (dep_id,)).fetchall()
    
    # Obtener el nombre del departamento para usar la plantilla específica
    departamento_info = conn.execute("SELECT nombre FROM departamentos WHERE id = ?", (dep_id,)).fetchone()
    conn.close()

    if not cajas:
        flash("No hay cajas en este departamento.")
        return redirect(url_for("cajas"))
    
    # Guardar el nombre del departamento para usar en la plantilla
    dept_name = departamento_info['nombre'].lower().replace(' ', '_') if departamento_info else 'default'
    
    # Renderizar la plantilla cover_department.html que incluye la plantilla específica del departamento
    # La plantilla cover_department.html ya tiene la lógica para intentar usar la plantilla del departamento
    # o usar default.html si no existe
    return render_template("cover/cover_department.html", cajas=cajas, dept_name=dept_name)




# ========================================================
# Rutas para impresión de portadas
# ========================================================
@app.route("/print-cover-caja", methods=["GET", "POST"])
@login_required
def print_cover_caja():
    if request.method == "POST":
        caja_id = request.form.get("caja_id")
        if caja_id:
            return redirect(url_for("cover_caja", caja_id=caja_id))
        else:
            flash("Por favor, seleccione una caja", "warning")
    
    # Obtener todas las cajas para el selector
    conn = get_db_connection()
    cajas = conn.execute("""
        SELECT cajas.id, cajas.id_caja, departamentos.nombre AS departamento
        FROM cajas
        LEFT JOIN departamentos ON cajas.departamento_id = departamentos.id
        ORDER BY CAST(cajas.id_caja AS INTEGER) ASC
    """).fetchall()
    conn.close()
    
    return render_template("print_cover_caja.html", cajas=cajas)

@app.route("/print-cover-department", methods=["GET", "POST"])
@login_required
def print_cover_department():
    if request.method == "POST":
        dep_id = request.form.get("departamento_id")
        if dep_id:
            return redirect(url_for("cover_department", dep_id=dep_id))
        else:
            flash("Por favor, seleccione un departamento", "warning")
    
    # Obtener todos los departamentos para el selector
    conn = get_db_connection()
    departamentos = conn.execute("SELECT id, nombre FROM departamentos ORDER BY nombre").fetchall()
    conn.close()
    
    return render_template("print_cover_department.html", departamentos=departamentos)

# ========================================================
# Inicio del Scheduler y ejecución de la aplicación
# ========================================================
def run_app():
    start_scheduler_thread()
    app.run(debug=True, port=5000, host='0.0.0.0')

if __name__ == "__main__":
    run_app()
