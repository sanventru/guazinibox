import sqlite3
import os

# Obtener la ruta de la base de datos
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'archivo.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def actualizar_tabla_cajas():
    print("Iniciando actualización de la tabla cajas...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verificar si la columna descripcion ya existe
    cursor.execute("PRAGMA table_info(cajas)")
    columnas = cursor.fetchall()
    columna_descripcion_existe = any(col['name'] == 'descripcion' for col in columnas)
    
    if columna_descripcion_existe:
        print("La columna 'descripcion' ya existe en la tabla cajas. No es necesario actualizarla.")
        conn.close()
        return
    
    # Paso 1: Crear una tabla temporal con la nueva estructura
    cursor.execute("""
        CREATE TABLE cajas_temp (
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
    
    # Paso 2: Copiar todos los datos de la tabla original a la temporal
    # La nueva columna descripcion se inicializará como NULL
    cursor.execute("""
        INSERT INTO cajas_temp (
            id, id_caja, departamento_id, años, tipo_id, observacion, 
            bodega_id, ubicacion_id, percha, fila, columna, qr_path
        )
        SELECT 
            id, id_caja, departamento_id, años, tipo_id, observacion, 
            bodega_id, ubicacion_id, percha, fila, columna, qr_path
        FROM cajas
    """)
    
    # Paso 3: Eliminar la tabla original
    cursor.execute("DROP TABLE cajas")
    
    # Paso 4: Renombrar la tabla temporal a la original
    cursor.execute("ALTER TABLE cajas_temp RENAME TO cajas")
    
    # Confirmar los cambios
    conn.commit()
    conn.close()
    
    print("¡Actualización completada con éxito!")
    print("Se ha agregado el campo 'descripcion' a la tabla cajas.")

if __name__ == "__main__":
    actualizar_tabla_cajas()
