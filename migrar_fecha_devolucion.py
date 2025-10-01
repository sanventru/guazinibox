import sqlite3

def migrar_fecha_devolucion():
    """Agrega la columna returned_date a la tabla prestamos"""
    conn = sqlite3.connect("archivo.db")
    cursor = conn.cursor()
    
    # Verificar si la columna ya existe
    cursor.execute("PRAGMA table_info(prestamos)")
    columnas = [info[1] for info in cursor.fetchall()]
    
    if 'returned_date' not in columnas:
        print("Agregando columna returned_date a la tabla prestamos...")
        cursor.execute("ALTER TABLE prestamos ADD COLUMN returned_date TEXT")
        conn.commit()
        print("✓ Columna agregada exitosamente")
    else:
        print("La columna returned_date ya existe")
    
    conn.close()

if __name__ == "__main__":
    migrar_fecha_devolucion()
