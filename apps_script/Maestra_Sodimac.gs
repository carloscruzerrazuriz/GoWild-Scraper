/**
 * Maestra Sodimac — Web App DEDICADO (aislado del System Manifest de telemetría).
 *
 * Recibe filas de producto de los engines Sodimac (MK7 / Maestra Sección / Fast)
 * y hace UPSERT por la llave (SKU × Tienda) en la hoja "Maestra Sodimac":
 * si la llave ya existe, sobrescribe la fila con lo nuevo (última info gana) y
 * refresca "Última Actualización"; si no, la agrega. Así la hoja es una maestra
 * que se auto-actualiza a medida que se usan los engines. SIN imágenes.
 *
 * DEPLOY (regla de oro §7 — nunca "Nueva implementación" tras la primera):
 *   1. Crear un Google Sheet nuevo (ej. "GoWild — Maestra Sodimac").
 *   2. Extensiones → Apps Script → pegar ESTE código → Guardar.
 *   3. Implementar → Nueva implementación → tipo "Aplicación web".
 *        - Ejecutar como: yo
 *        - Quién tiene acceso: Cualquier usuario
 *   4. Copiar la URL /exec y pasársela a la IA para cablearla en _maestra_post.py.
 *   Para ACTUALIZAR el código luego: editar → Guardar → Implementar → Administrar
 *   implementaciones → editar la ACTIVA (lápiz) → Versión: "Nueva versión" →
 *   Implementar. La URL NO cambia.
 */

var SHEET_NAME = "Maestra Sodimac";
var TOKEN = "mS7_kR2vQ9xL4pN8wYtZ-bF3hGcE6uA1";  // secreto compartido con _maestra_post.py

// Orden fijo de columnas. Llave = SKU (col A) + Tienda (col B).
var COLS = [
  "SKU", "Tienda", "SKU Easy", "Nombre Tienda", "Región", "Zona",
  "Sección", "Subcategoría", "Marca", "Descripción", "Vendedor",
  "Precio Normal", "Precio Internet", "% Descuento",
  "Precio Mayorista", "Descuento Mayorista", "Todos los Precios",
  "URL", "Fuente", "Última Actualización"
];

function doGet(e) {
  return ContentService.createTextOutput("Maestra Sodimac OK");
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);            // serializa escrituras concurrentes de varios usuarios
  try {
    var d = JSON.parse(e.postData.contents);
    if (d.token !== TOKEN)             return _json({ ok: false, error: "bad token" });
    if (d.type !== "maestra_sodimac")  return _json({ ok: false, error: "unknown type" });
    var res = upsert_(d.rows || []);
    return _json({ ok: true, updated: res.updated, added: res.added });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function _sheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.appendRow(COLS);
    sh.getRange(1, 1, 1, COLS.length).setFontWeight("bold");
    sh.setFrozenRows(1);
  }
  return sh;
}

function upsert_(rows) {
  if (!rows.length) return { updated: 0, added: 0 };
  var sh = _sheet_();
  var lastRow = sh.getLastRow();

  // Índice (SKU|Tienda) -> nº de fila. Se lee las 2 primeras columnas de una sola vez.
  var index = {};
  if (lastRow > 1) {
    var keys = sh.getRange(2, 1, lastRow - 1, 2).getValues();
    for (var i = 0; i < keys.length; i++) {
      index[keys[i][0] + "|" + keys[i][1]] = i + 2;
    }
  }

  // Dedup del batch entrante por llave (la última fila del batch gana).
  var batch = {};
  for (var j = 0; j < rows.length; j++) {
    var r = rows[j];
    var vals = COLS.map(function (c) { return (r[c] != null) ? r[c] : ""; });
    batch[String(r["SKU"] || "") + "|" + String(r["Tienda"] || "")] = vals;
  }

  var appends = [], updated = 0;
  for (var k in batch) {
    if (index[k]) {
      sh.getRange(index[k], 1, 1, COLS.length).setValues([batch[k]]);
      updated++;
    } else {
      appends.push(batch[k]);
    }
  }
  if (appends.length) {
    sh.getRange(sh.getLastRow() + 1, 1, appends.length, COLS.length).setValues(appends);
  }
  return { updated: updated, added: appends.length };
}

function _json(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}
