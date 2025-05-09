import sqlite3

def get_db_connection():
    conn = sqlite3.connect("archivo.db")
    conn.row_factory = sqlite3.Row
    return conn

def migrar_tamano():
    """
    Script para migrar el campo 'tamano' de la tabla 'ubicaciones' a la tabla 'bodegas'.
    Este script debe ejecutarse una sola vez después de modificar la estructura de las tablas.
    """
    print("Iniciando migración de datos de tamaño...")
    
    conn = get_db_connection()
    
    # 1. Verificar si la columna tamano existe en la tabla ubicaciones
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(ubicaciones)")
    columns = cursor.fetchall()
    
    tamano_exists = any(column['name'] == 'tamano' for column in columns)
    
    if not tamano_exists:
        print("La columna 'tamano' ya no existe en la tabla 'ubicaciones'. No es necesario migrar.")
        conn.close()
        return
    
    # 2. Obtener los datos actuales
    ubicaciones = conn.execute("SELECT * FROM ubicaciones").fetchall()
    
    # 3. Crear una copia de seguridad de la tabla ubicaciones
    print("Creando copia de seguridad de la tabla ubicaciones...")
    conn.execute("CREATE TABLE IF NOT EXISTS ubicaciones_backup AS SELECT * FROM ubicaciones")
    
    # 4. Actualizar la tabla bodegas para asegurarse de que tiene la columna tamano
    cursor.execute("PRAGMA table_info(bodegas)")
    columns = cursor.fetchall()
    
    if not any(column['name'] == 'tamano' for column in columns):
        print("Agregando columna 'tamano' a la tabla 'bodegas'...")
        conn.execute("ALTER TABLE bodegas ADD COLUMN tamano TEXT")
    
    # 5. Crear una tabla temporal para las ubicaciones sin el campo tamano
    print("Creando tabla temporal para ubicaciones sin el campo tamano...")
    conn.execute("CREATE TABLE ubicaciones_temp (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL)")
    
    # 6. Insertar los datos en la tabla temporal
    for ubicacion in ubicaciones:
        conn.execute("INSERT INTO ubicaciones_temp (id, nombre) VALUES (?, ?)", 
                    (ubicacion['id'], ubicacion['nombre']))
    
    # 7. Eliminar la tabla original y renombrar la temporal
    print("Reemplazando tabla de ubicaciones...")
    conn.execute("DROP TABLE ubicaciones")
    conn.execute("ALTER TABLE ubicaciones_temp RENAME TO ubicaciones")
    
    print("Migración completada con éxito.")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrar_tamano()
