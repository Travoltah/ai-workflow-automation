// NODE: "Verify briefs"  (Code node, mode: Run Once for All Items)
// The model proposes; the code decides. For each brief:
//   - every quote (dates, obligations) must appear WORD FOR WORD in the document or its changed passages
//   - every key date must be a real YYYY-MM-DD date, and its quote must state that year and day
//   - every affected control must exist in the control library
//   - the brief must be complete: obligations or controls, and how it affects the company
// Anything that fails is removed and listed in "verification"; the brief is then "flagged" for the
// reviewer instead of "analysed". A failed call gets a fallback brief, also flagged.
// Applicability and priority are calculated here from the company profile, not by the model.

const data = $('Load changes').first().json.data;
const requests = $('One item per brief').all().map((i) => i.json);
const responses = $input.all().map((i) => i.json);
const changes = new Map(data.changes.map((c) => [c.change_id, c]));
const controlIds = new Set(data.controls.map((c) => c.control_id));
const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

// Word-for-word, but tolerant of whitespace, case, curly quotes and dash variants.
const norm = (s) => String(s || '').toLowerCase().replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
  .replace(/[–—]/g, '-').replace(/\s+/g, ' ').trim();
const quoteFound = (quote, source) => norm(quote).length >= 12 && source.includes(norm(quote));

const dateCheck = (d, quote) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d || '');
  if (!m) return 'not a YYYY-MM-DD date';
  const date = new Date(`${d}T00:00:00Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== d) return 'not a real calendar date';
  const q = norm(quote);
  const day = String(Number(m[3]));
  const month = MONTHS[Number(m[2]) - 1];
  if (!q.includes(m[1])) return `the quote does not state the year ${m[1]}`;
  if (!new RegExp(`(^|\\D)${day}(\\D|$)`).test(q) || !(q.includes(month) || q.includes(`${m[1]}-${m[2]}`))) return 'the quote does not state that day and month';
  return null;
};

const briefs = requests.map((req, i) => {
  const c = changes.get(req.change_id);
  const res = responses[i] || {};
  const source = norm(`${c.document_text}\n${c.diff_text}`);
  const removed = [];
  let brief = null;

  if (res.error) removed.push(`Claude call failed: ${JSON.stringify(res.error).slice(0, 200)}`);
  else if (res.stop_reason !== 'end_turn') removed.push(`Answer incomplete (${res.stop_reason})`);
  else {
    try { brief = JSON.parse(res.content.find((b) => b.type === 'text').text); }
    catch (e) { removed.push(`Answer was not valid JSON: ${e.message}`); }
  }

  if (brief) {
    brief.key_dates = brief.key_dates.filter((k) => {
      if (!quoteFound(k.quote, source)) { removed.push(`date ${k.date}: quote not found in the document`); return false; }
      const problem = dateCheck(k.date, k.quote);
      if (problem) { removed.push(`date ${k.date}: ${problem}`); return false; }
      return true;
    });
    brief.obligations = brief.obligations.filter((o) => {
      if (quoteFound(o.quote, source)) return true;
      removed.push(`obligation "${String(o.text).slice(0, 80)}": quote not found in the document`);
      return false;
    });
    const seen = new Set();
    brief.affected_controls = brief.affected_controls.filter((a) => {
      if (!controlIds.has(a.control_id)) { removed.push(`control ${a.control_id}: not in the control library`); return false; }
      if (seen.has(a.control_id)) return false;
      seen.add(a.control_id);
      return true;
    });
    if (!String(brief.summary || '').trim()) removed.push('empty summary');
    // Completeness: a brief on a relevant change must say what to do. (Found in live run #2: a brief with a
    // good summary but no obligations, no controls and no relevance passed every accuracy check.)
    if (!brief.obligations.length && !brief.affected_controls.length) removed.push('incomplete: no verified obligations and no controls');
    if (!String(brief.relevance_to_company || '').trim()) removed.push('incomplete: relevance to the company is empty');
  } else {
    brief = {
      summary: 'Not analysed: the AI brief was missing or failed the automatic check. Read the publication directly.',
      what_changed: '', instrument_type: 'other', status: 'unknown', binding: 'unknown',
      key_dates: [], obligations: [], affected_controls: [], relevance_to_company: '', recommended_actions: [], confidence: 'low',
    };
  }

  const p = data.profile;
  const applicability = p.markets.includes(c.jurisdiction) ? 'in_market' : p.watch_markets.includes(c.jurisdiction) ? 'watch_market' : 'out_of_scope';
  const substantive = brief.affected_controls.length > 0 || brief.obligations.length > 0;
  const priority = applicability === 'in_market' ? (substantive ? 'high' : 'medium')
    : applicability === 'watch_market' ? (substantive ? 'medium' : 'low') : 'low';

  return {
    change_id: req.change_id,
    status: removed.length ? 'flagged' : 'analysed',
    applicability, priority,
    brief: { ...brief, model: req.anthropicRequest.model },
    verification: { passed: removed.length === 0, removed,
      checked: { dates: brief.key_dates.length, obligations: brief.obligations.length, controls: brief.affected_controls.length } },
    usage: res.usage || null,
  };
});

return [{ json: { briefs } }];
