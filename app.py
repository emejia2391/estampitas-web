import os
from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cambia-esta-clave')

# Puedes dejar tu conexión en variable de entorno DATABASE_URL.
# Si no existe, usa esta conexión por defecto.
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgres://019e476f-3e92-74b3-93c1-495cf509fe3a:2b34922a-2343-4b04-9b25-4730f61fff6c@us-west-2.db.thenile.dev:5432/Estampitas?sslmode=require'
)

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def recalcular_stock(cur, cod_estampa):
    cur.execute(
        """
        UPDATE estampitas
        SET stock = COALESCE(inventario, 0) - COALESCE(venta, 0)
        WHERE cod_estampa = %s
        """,
        (cod_estampa,)
    )

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    with get_conn() as conn:
        with conn.cursor() as cur:
            if q:
                cur.execute(
                    """
                    SELECT cod_estampa, nombre, seleccion, inventario, venta, stock
                    FROM estampitas
                    WHERE cod_estampa ILIKE %s OR nombre ILIKE %s OR seleccion ILIKE %s
                    ORDER BY cod_estampa
                    LIMIT 100
                    """,
                    (f'%{q}%', f'%{q}%', f'%{q}%')
                )
            else:
                cur.execute(
                    """
                    SELECT cod_estampa, nombre, seleccion, inventario, venta, stock
                    FROM estampitas
                    ORDER BY cod_estampa
                    LIMIT 100
                    """
                )
            estampitas = cur.fetchall()

            cur.execute("SELECT COALESCE(SUM(inventario),0) AS total FROM estampitas")
            total_inventario = cur.fetchone()['total']

            cur.execute("SELECT COALESCE(SUM(venta),0) AS total FROM estampitas")
            total_venta = cur.fetchone()['total']

            cur.execute("SELECT COALESCE(SUM(stock),0) AS total FROM estampitas")
            total_stock = cur.fetchone()['total']

    return render_template(
        'index.html',
        estampitas=estampitas,
        q=q,
        total_inventario=total_inventario,
        total_venta=total_venta,
        total_stock=total_stock
    )

@app.route('/ingresar', methods=['POST'])
def ingresar():
    cod_estampa = request.form.get('cod_estampa', '').strip().upper()
    cantidad = request.form.get('cantidad', '0').strip()

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        flash('La cantidad de ingreso debe ser un número entero mayor a 0.', 'error')
        return redirect(url_for('index'))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cod_estampa FROM estampitas WHERE cod_estampa = %s", (cod_estampa,))
            existe = cur.fetchone()

            if not existe:
                flash(f'No existe la estampita {cod_estampa}.', 'error')
                return redirect(url_for('index'))

            cur.execute(
                """
                UPDATE estampitas
                SET inventario = COALESCE(inventario, 0) + %s
                WHERE cod_estampa = %s
                """,
                (cantidad, cod_estampa)
            )
            recalcular_stock(cur, cod_estampa)
            conn.commit()

    flash(f'Se ingresaron {cantidad} unidades de {cod_estampa}.', 'ok')
    return redirect(url_for('index', q=cod_estampa))

@app.route('/vender', methods=['POST'])
def vender():
    cod_estampa = request.form.get('cod_estampa', '').strip().upper()
    cantidad = request.form.get('cantidad', '0').strip()

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        flash('La cantidad de venta debe ser un número entero mayor a 0.', 'error')
        return redirect(url_for('index'))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cod_estampa, COALESCE(stock, 0) AS stock
                FROM estampitas
                WHERE cod_estampa = %s
                """,
                (cod_estampa,)
            )
            item = cur.fetchone()

            if not item:
                flash(f'No existe la estampita {cod_estampa}.', 'error')
                return redirect(url_for('index'))

            if item['stock'] < cantidad:
                flash(f'No hay suficiente stock de {cod_estampa}. Stock actual: {item["stock"]}.', 'error')
                return redirect(url_for('index', q=cod_estampa))

            cur.execute(
                """
                UPDATE estampitas
                SET venta = COALESCE(venta, 0) + %s
                WHERE cod_estampa = %s
                """,
                (cantidad, cod_estampa)
            )
            recalcular_stock(cur, cod_estampa)
            conn.commit()

    flash(f'Venta registrada: {cantidad} unidades de {cod_estampa}.', 'ok')
    return redirect(url_for('index', q=cod_estampa))

@app.route('/recalcular')
def recalcular_todo():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE estampitas
                SET stock = COALESCE(inventario, 0) - COALESCE(venta, 0)
                """
            )
            conn.commit()
    flash('Stock recalculado correctamente.', 'ok')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
