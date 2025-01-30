import sqlite3

def print_database_contents():
    conn = sqlite3.connect("invoices.db")
    cursor = conn.cursor()
    
    # Retrieve all records from the invoices table
    cursor.execute("SELECT * FROM invoices;")
    rows = cursor.fetchall()
    
    # Print the column names
    column_names = [description[0] for description in cursor.description]
    print(f"{' | '.join(column_names)}")
    print("-" * 50)  # Separator line
    
    # Print each row
    for row in rows:
        print(" | ".join(str(value) for value in row))
    
    conn.close()

# Call the function to print the database contents
print_database_contents()