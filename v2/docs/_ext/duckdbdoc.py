"""Sphinx directives that read the finished database at build time.

The schema chapter of this manual is not written by hand. It is generated from
``duckdb_tables()``, ``duckdb_columns()`` and the ``COMMENT ON`` text stored in
the database itself, so the manual cannot describe a column that no longer
exists or miss one that was added. Likewise the recipes are executed, not
quoted: the SQL shown and the SQL run are the same bytes of the same file.

A pre-build script could produce the same rST, and autodoc could describe the
Python that emits the DDL. Neither would describe *the artefact a reader
downloads*, which is the only thing this manual is about.

Directives
----------
``.. duckdb-schema::``
    Every base table, or those named in ``:tables:``, as a section with the
    table comment and a column table. ``:views:`` switches to the views.
``.. sql-recipe:: name.sql``
    Show ``_sql/name.sql`` and the first rows of its result.
``.. duckdb-params:: <family>``
    The definition of one distribution family from ``meta_fit_family``.
``:dbq:`SELECT ...```
    An inline scalar, so a number in the prose comes from the database.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from docutils import nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import StringList
from sphinx.util import logging
from sphinx.util.nodes import nested_parse_with_titles

logger = logging.getLogger(__name__)

_CONNECTIONS: dict[str, duckdb.DuckDBPyConnection] = {}


def _connect(env) -> duckdb.DuckDBPyConnection:
    path = env.config.duckdbdoc_database
    if path not in _CONNECTIONS:
        if not Path(path).exists():
            raise FileNotFoundError(
                f"{path} not found. Build it first:\n"
                "    cd v2 && PYTHONPATH=.:../research python -m jpduck.build --stage all"
            )
        _CONNECTIONS[path] = duckdb.connect(path, read_only=True)
    return _CONNECTIONS[path]


def _rst(directive: Directive, text: str) -> list[nodes.Node]:
    """Parse generated rST in the calling document's context."""
    node = nodes.section()
    node.document = directive.state.document
    lines = StringList(text.splitlines(), source="<duckdbdoc>")
    nested_parse_with_titles(directive.state, lines, node)
    return node.children


def _escape(text: str | None) -> str:
    """Make a comment safe inside a list-table cell."""
    if not text:
        return ""
    return text.replace("|", r"\|").replace("\n", " ").strip()


def _fmt(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


# --------------------------------------------------------------- schema ----
_SCHEMA_QUERY = """
SELECT c.table_name, c.column_name, c.data_type, c.comment, c.column_index
FROM duckdb_columns() c
JOIN duckdb_{kind}() t
  ON t.database_name = c.database_name AND t.schema_name = c.schema_name
 AND t.{namecol} = c.table_name
WHERE c.database_name = current_database() AND c.schema_name = 'main'
  AND NOT c.internal
ORDER BY c.table_name, c.column_index
"""


class DuckdbSchema(Directive):
    has_content = False
    option_spec = {
        "tables": directives.unchanged,
        "views": directives.flag,
        "titles": directives.unchanged,   # "section" (default) or "rubric"
    }

    def run(self) -> list[nodes.Node]:
        env = self.state.document.settings.env
        con = _connect(env)
        env.note_dependency(env.config.duckdbdoc_database)

        is_view = "views" in self.options
        kind, namecol = ("views", "view_name") if is_view else ("tables", "table_name")
        rows = con.execute(_SCHEMA_QUERY.format(kind=kind, namecol=namecol)).fetchall()

        objects = con.execute(
            f"SELECT {namecol}, comment FROM duckdb_{kind}() "
            "WHERE database_name = current_database() AND schema_name = 'main' "
            "AND NOT internal ORDER BY 1"
        ).fetchall()
        described = {name: comment for name, comment in objects}

        wanted = [t.strip() for t in self.options.get("tables", "").split(",") if t.strip()]
        if wanted:
            missing = [t for t in wanted if t not in described]
            if missing:
                logger.warning("duckdb-schema: no such %s: %s", kind, missing,
                               location=(env.docname, self.lineno))
            names = [t for t in wanted if t in described]
        else:
            names = list(described)

        marker = "^" if self.options.get("titles", "section") == "section" else None
        counts = dict(con.execute(
            f"SELECT {namecol}, "
            + ("NULL" if is_view else "estimated_size")
            + f" FROM duckdb_{kind}() WHERE database_name = current_database()"
        ).fetchall()) if not is_view else {}

        out: list[str] = []
        for name in names:
            cols = [r for r in rows if r[0] == name]
            if not cols:
                continue
            if marker:
                out += [f"``{name}``", marker * (len(name) + 4), ""]
            else:
                out += [f".. rubric:: ``{name}``", ""]
            if described[name]:
                out += [_escape(described[name]), ""]
            else:
                logger.warning("%s %s has no COMMENT ON", kind[:-1], name,
                               location=(env.docname, self.lineno))
            if not is_view and counts.get(name) is not None:
                out += [f"行数 {counts[name]:,}。", ""]

            out += [".. container:: schema-table", "",
                    "   .. list-table::",
                    "      :header-rows: 1",
                    "      :widths: 24 26 50",
                    "",
                    "      * - 列", "        - 型", "        - 説明"]
            for _t, column, dtype, comment, _i in cols:
                if not comment and not is_view:
                    logger.warning("%s.%s has no COMMENT ON", name, column,
                                   location=(env.docname, self.lineno))
                out += [f"      * - ``{column}``",
                        f"        - ``{dtype}``",
                        f"        - {_escape(comment) or '(ビューの列。元の列の説明を参照)'}"]
            out += [""]
        return _rst(self, "\n".join(out))


# --------------------------------------------------------------- recipe ----
class SqlRecipe(Directive):
    required_arguments = 1
    has_content = True
    option_spec = {
        "caption": directives.unchanged,
        "limit": directives.nonnegative_int,
        "no-run": directives.flag,
        "hide-sql": directives.flag,
    }

    def run(self) -> list[nodes.Node]:
        env = self.state.document.settings.env
        path = Path(env.config.duckdbdoc_sql_dir) / self.arguments[0]
        if not path.exists():
            raise self.error(f"sql-recipe: {path} not found")
        env.note_dependency(str(path))
        sql = path.read_text(encoding="utf-8").strip()

        out: list[str] = []
        if self.content:
            out += list(self.content) + [""]
        if "hide-sql" not in self.options:
            caption = self.options.get("caption", path.name)
            out += [".. code-block:: sql", f"   :caption: {caption}", ""]
            out += [f"   {line}" for line in sql.splitlines()] + [""]

        if "no-run" not in self.options:
            con = _connect(env)
            env.note_dependency(env.config.duckdbdoc_database)
            limit = self.options.get("limit", 8)
            try:
                cur = con.execute(sql)
                headers = [d[0] for d in cur.description]
                rows = cur.fetchmany(limit + 1)
            except Exception as exc:  # a broken recipe must fail the build
                raise self.error(f"sql-recipe {path.name} failed: {exc}") from exc
            truncated = len(rows) > limit
            rows = rows[:limit]

            body = [[_escape(_fmt(v)) for v in row] for row in rows]
            # Without explicit widths, LaTeX's tabulary lets one long cell
            # squeeze the others until even a short identifier no longer fits
            # its column. Size each column by its own widest entry instead.
            # One 240-character cell would otherwise take four fifths of the
            # page and starve the rest, so a column's weight is capped.
            # A header with an underscore or a hyphen can be broken across
            # lines, so its column may be narrow. One that cannot be broken
            # needs the whole word to fit, and gets more slack.
            widths = [
                min(max([len(h) + (10 if ("_" in h or "-" in h) else 14)]
                        + [len(r[i]) for r in body]), 40)
                for i, h in enumerate(headers)
            ]
            out += [".. container:: schema-table", "",
                    "   .. list-table:: 実行結果",
                    "      :header-rows: 1",
                    "      :widths: " + " ".join(str(w) for w in widths), ""]
            out += ["      * - " + ("\n        - ".join(f"``{h}``" for h in headers))]
            for cells in body:
                out += ["      * - " + ("\n        - ".join(cells))]
            out += [""]
            if truncated:
                out += [f"最初の {limit} 行のみ。", ""]
        return _rst(self, "\n".join(out))


# --------------------------------------------------------------- params ----
_PARAM_FIELDS = [
    ("support", "台"),
    ("density_unit", "密度の単位"),
    ("n_params", "自由パラメータ数"),
    ("param_columns", "パラメータを収めた列"),
    ("pdf_plain", "確率密度"),
    ("cdf_plain", "累積分布"),
    ("ppf_plain", "分位点関数 (逆関数法に使う)"),
    ("loglik_plain", "対数尤度"),
    ("estimator", "推定法"),
    ("estimator_note", "推定の注記"),
    ("gof_stat", "適合度統計量"),
    ("scipy_equivalent", "scipy の対応物"),
    ("reference", "出典"),
]


class DuckdbParams(Directive):
    required_arguments = 1
    optional_arguments = 1  # quantity, when a family is fitted to both
    option_spec = {"latex": directives.flag}

    def run(self) -> list[nodes.Node]:
        env = self.state.document.settings.env
        con = _connect(env)
        env.note_dependency(env.config.duckdbdoc_database)
        family = self.arguments[0]
        quantity = self.arguments[1] if len(self.arguments) > 1 else None

        sql = "SELECT * FROM meta_fit_family WHERE family = ?"
        args: list[object] = [family]
        if quantity:
            sql += " AND quantity = ?"
            args.append(quantity)
        cur = con.execute(sql, args)
        cols = [d[0] for d in cur.description]
        found = cur.fetchall()
        if not found:
            raise self.error(f"duckdb-params: no meta_fit_family row for {family!r}")
        if len(found) > 1:
            raise self.error(
                f"duckdb-params: {family!r} is fitted to several quantities; "
                "name one as the second argument"
            )
        row = dict(zip(cols, found[0], strict=True))

        out: list[str] = []
        if not row["included"]:
            out += [".. warning::", "",
                    f"   この族は当てはめていません。{_escape(row['exclusion_reason'])}", ""]
        if "latex" in self.options and row.get("pdf_latex"):
            out += [".. math::", "", f"   {row['pdf_latex']}", ""]
        for key, label in _PARAM_FIELDS:
            value = row.get(key)
            if value in (None, ""):
                continue
            body = _escape(_fmt(value))
            verbatim = key in {
                "pdf_plain", "cdf_plain", "ppf_plain", "loglik_plain",
                "param_columns", "scipy_equivalent", "support",
            }
            if verbatim and len(body) > 66:
                # A long formula has no break points and would run past the
                # margin as an inline literal; give it a block of its own.
                out += [f":{label}:", "",
                        "   .. code-block:: text", "",
                        f"      {body}", ""]
            else:
                out += [f":{label}:", f"   {'``' + body + '``' if verbatim else body}"]
        out += [""]
        return _rst(self, "\n".join(out))


# ----------------------------------------------------------------- role ----
def dbq_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    """``:dbq:`SELECT ...``` -- one scalar, straight from the database."""
    env = inliner.document.settings.env
    con = _connect(env)
    env.note_dependency(env.config.duckdbdoc_database)
    try:
        value = con.execute(text).fetchone()[0]
    except Exception as exc:
        msg = inliner.reporter.error(f"dbq failed: {exc}", line=lineno)
        return [inliner.problematic(rawtext, rawtext, msg)], [msg]
    rendered = f"{value:,}" if isinstance(value, int) else _fmt(value)
    return [nodes.literal(rawtext, rendered)], []


def setup(app):
    app.add_config_value("duckdbdoc_database", "", "env")
    app.add_config_value("duckdbdoc_sql_dir", "", "env")
    app.add_directive("duckdb-schema", DuckdbSchema)
    app.add_directive("sql-recipe", SqlRecipe)
    app.add_directive("duckdb-params", DuckdbParams)
    app.add_role("dbq", dbq_role)
    return {"version": "1.0", "parallel_read_safe": False, "parallel_write_safe": True}
