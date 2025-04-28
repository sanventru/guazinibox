import sqlite3
import os

# Obtener la ruta de la base de datos
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'archivo.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def actualizar_tabla_usuarios():
    print("Iniciando actualización de la tabla usuarios...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verificar si las columnas ya existen
    cursor.execute("PRAGMA table_info(users)")
    columnas = cursor.fetchall()
    columnas_existentes = [col['name'] for col in columnas]
    
    if 'email' in columnas_existentes and 'reset_token' in columnas_existentes and 'token_expiry' in columnas_existentes:
        print("Las columnas ya existen en la tabla users. No es necesario actualizarla.")
        conn.close()
        return
    
    # Paso 1: Crear una tabla temporal con la nueva estructura
    cursor.execute("""
        CREATE TABLE users_temp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE,
            reset_token TEXT,
            token_expiry TIMESTAMP
        )
    """)
    
    # Paso 2: Copiar todos los datos de la tabla original a la temporal
    cursor.execute("""
        INSERT INTO users_temp (id, username, password)
        SELECT id, username, password FROM users
    """)
    
    # Paso 3: Eliminar la tabla original
    cursor.execute("DROP TABLE users")
    
    # Paso 4: Renombrar la tabla temporal a la original
    cursor.execute("ALTER TABLE users_temp RENAME TO users")
    
    # Confirmar los cambios
    conn.commit()
    conn.close()
    
    print("¡Actualización completada con éxito!")
    print("Se han agregado los campos 'email', 'reset_token' y 'token_expiry' a la tabla users.")

if __name__ == "__main__":
    actualizar_tabla_usuarios()
