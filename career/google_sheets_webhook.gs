/**
 * Live sync endpoint for "Job Pipeline Tracker – A.B.M. Ataullah".
 *
 * Setup (one time, about 2 minutes):
 *   1. Open the Sheet → Extensions → Apps Script. Delete the sample code and paste this whole file.
 *   2. Deploy → New deployment → type "Web app".
 *        Execute as: Me      Who has access: Anyone
 *   3. Authorize, copy the Web app URL (ends in /exec) and paste it into
 *        career/sheets_config.json  →  "webhook_sync_url"
 *
 * The office posts JSON like:
 *   {"token": "...", "sheet": "Apply Queue", "key": "Apply link", "rows": [{...}, ...]}
 * Each row is upserted by its key column; new columns are added if a row has fields the sheet lacks.
 */
const TOKEN = 'CHANGE_ME';  // must match "webhook_token" in sheets_config.json

function doPost(e) {
  const body = JSON.parse(e.postData.contents || '{}');
  if (body.token !== TOKEN) return reply({ok: false, error: 'bad token'});
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(body.sheet) || ss.insertSheet(body.sheet);
  const key = body.key;
  const rows = body.rows || [];
  if (!rows.length) return reply({ok: true, written: 0});

  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    let headers = sheet.getLastColumn() ? sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0] : [];
    rows.forEach(r => Object.keys(r).forEach(k => { if (headers.indexOf(k) < 0) headers.push(k); }));
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    sheet.setFrozenRows(1);

    const keyCol = headers.indexOf(key);
    const last = sheet.getLastRow();
    const existing = last > 1 ? sheet.getRange(2, keyCol + 1, last - 1, 1).getValues().map(v => String(v[0])) : [];
    let written = 0;
    rows.forEach(r => {
      const values = headers.map(h => (r[h] === undefined || r[h] === null) ? '' : r[h]);
      const idx = existing.indexOf(String(r[key]));
      if (idx >= 0) {
        // keep cells the office does not send (e.g. your own notes in extra columns)
        const range = sheet.getRange(idx + 2, 1, 1, headers.length);
        const cur = range.getValues()[0];
        range.setValues([headers.map((h, i) => (h in r) ? values[i] : cur[i])]);
      } else {
        sheet.appendRow(values);
        existing.push(String(r[key]));
      }
      written++;
    });
    return reply({ok: true, written: written});
  } finally {
    lock.releaseLock();
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
