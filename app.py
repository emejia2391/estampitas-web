import os
from urllib.parse import urlparse, parse_qs

from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
from psycopg2.extras import RealDictCursor


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave")


def get_database_url():
    """
    Render debe tener esta variable en Environment:
    DATABASE_URL=postgres://usuario:password@host:5432/Estampitas?sslmode=require
    """
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "Falta configurar DATABASE_URL en Render > Environment."
        )

    return database_url


def get_conn():
    database_url = get_database_url()

    # Nile/PostgreSQL en la nube normalmente necesita SSL.
    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def recalcular_stock(cur, cod_estampa):
    cur.execute(
        """
        UPDATE estampitas
        SET stock = COALESCE(inventario, 0) - COALESCE(venta, 0)
        WHERE cod_estampa = %s
        """,
        (cod_estampa,)
    )


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    ordenar = request.args.get("ordenar", "cod_estampa").strip()

    columnas_validas = {
        "cod_estampa": "cod_estampa",
        "nombre": "nombre",
        "seleccion": "seleccion"
    }

    ordenar_sql = columnas_validas.get(ordenar, "cod_estampa")

    total_inventario = 0
    total_venta = 0
    total_stock = 0
    estampitas = []

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if q:
                    filtros = (f"%{q}%", f"%{q}%", f"%{q}%")

                    cur.execute(
                        f"""
                        SELECT cod_estampa, nombre, seleccion,
                               COALESCE(inventario, 0) AS inventario,
                               COALESCE(venta, 0) AS venta,
                               COALESCE(stock, 0) AS stock
                        FROM estampitas
                        WHERE cod_estampa ILIKE %s
                           OR nombre ILIKE %s
                           OR seleccion ILIKE %s
                        ORDER BY {ordenar_sql}
                        LIMIT 300
                        """,
                        filtros
                    )
                    estampitas = cur.fetchall()

                    cur.execute(
                        """
                        SELECT
                            COALESCE(SUM(inventario), 0) AS total_inventario,
                            COALESCE(SUM(venta), 0) AS total_venta,
                            COALESCE(SUM(stock), 0) AS total_stock
                        FROM estampitas
                        WHERE cod_estampa ILIKE %s
                           OR nombre ILIKE %s
                           OR seleccion ILIKE %s
                        """,
                        filtros
                    )
                    totales = cur.fetchone()
                    total_inventario = totales["total_inventario"]
                    total_venta = totales["total_venta"]
                    total_stock = totales["total_stock"]

                else:
                    cur.execute("SELECT COALESCE(SUM(inventario), 0) AS total FROM estampitas")
                    total_inventario = cur.fetchone()["total"]

                    cur.execute("SELECT COALESCE(SUM(venta), 0) AS total FROM estampitas")
                    total_venta = cur.fetchone()["total"]

                    cur.execute("SELECT COALESCE(SUM(stock), 0) AS total FROM estampitas")
                    total_stock = cur.fetchone()["total"]

    except Exception as e:
        return f"""
        <h1>Error conectando con la base de datos</h1>
        <p>{str(e)}</p>
        <p>Revisa que DATABASE_URL esté configurado en Render y que la tabla estampitas exista.</p>
        """, 500

    return render_template(
        "index.html",
        estampitas=estampitas,
        q=q,
        ordenar=ordenar,
        total_inventario=total_inventario,
        total_venta=total_venta,
        total_stock=total_stock
    )


@app.route("/ingresar", methods=["POST"])
def ingresar():
    cod_estampa = request.form.get("cod_estampa", "").strip().upper()
    cantidad = request.form.get("cantidad", "0").strip()

    if not cod_estampa:
        flash("Debes ingresar el código de la estampita.", "error")
        return redirect(url_for("index"))

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        flash("La cantidad de ingreso debe ser un número entero mayor a 0.", "error")
        return redirect(url_for("index", q=cod_estampa))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cod_estampa FROM estampitas WHERE cod_estampa = %s",
                (cod_estampa,)
            )
            existe = cur.fetchone()

            if not existe:
                flash(f"No existe la estampita {cod_estampa}.", "error")
                return redirect(url_for("index", q=cod_estampa))

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

    flash(f"Se ingresaron {cantidad} unidades de {cod_estampa}.", "ok")
    return redirect(url_for("index", q=cod_estampa))


@app.route("/vender", methods=["POST"])
def vender():
    cod_estampa = request.form.get("cod_estampa", "").strip().upper()
    cantidad = request.form.get("cantidad", "0").strip()

    if not cod_estampa:
        flash("Debes ingresar el código de la estampita.", "error")
        return redirect(url_for("index"))

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        flash("La cantidad de venta debe ser un número entero mayor a 0.", "error")
        return redirect(url_for("index", q=cod_estampa))

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
                flash(f"No existe la estampita {cod_estampa}.", "error")
                return redirect(url_for("index", q=cod_estampa))

            if item["stock"] < cantidad:
                flash(
                    f"No hay suficiente stock de {cod_estampa}. Stock actual: {item['stock']}.",
                    "error"
                )
                return redirect(url_for("index", q=cod_estampa))

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

    flash(f"Venta registrada: {cantidad} unidades de {cod_estampa}.", "ok")
    return redirect(url_for("index", q=cod_estampa))


@app.route("/recalcular")
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

    flash("Stock recalculado correctamente.", "ok")
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(debug=True)
