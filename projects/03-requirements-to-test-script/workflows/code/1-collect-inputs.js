// NODE: "Collect inputs"  (Code node, mode: Run Once for All Items)
// Brings the form and the API into one shape: the files to read, the Jira stories that
// already exist, and what the run is allowed to do in Jira.

const settings = $('Settings').first().json;
const item = $input.first();
const fromForm = $('Upload requirements').isExecuted;
const input = fromForm ? item.json : (item.json.body ?? {});

// Jira keys: "CPAY-12, cpay-14" or ["CPAY-12"] -> ["CPAY-12", "CPAY-14"]
const jiraKeys = [...new Set(
  [].concat(input[fromForm ? 'Existing Jira stories' : 'jiraStories'] ?? [])
    .flatMap((value) => String(value).split(/[\s,;]+/))
    .map((key) => key.trim().toUpperCase())
    .filter(Boolean),
)];
const badKeys = jiraKeys.filter((key) => !/^[A-Z][A-Z0-9_]+-\d+$/.test(key));
if (badKeys.length) throw new Error(`These are not Jira issue keys: ${badKeys.join(', ')}. Use the form PROJ-123.`);

const createChoice = fromForm ? String(input['Create Jira tickets'] ?? '') : input.createJiraTickets;
const createInJira = fromForm ? createChoice.startsWith('Yes') : createChoice === true;
const projectKey = String(input[fromForm ? 'Jira project key' : 'jiraProjectKey'] || settings.jiraProjectKey || '')
  .trim().toUpperCase();
const figmaUrls = String(input[fromForm ? 'Figma link' : 'figmaUrl'] ?? '')
  .split(/\s+/).filter((url) => /^https:\/\/(www\.)?figma\.com\//.test(url));

// Files. The form delivers them as binary data ("Requirements_documents_0", "Wireframes_1", ...).
// The API takes base64: { documents: [{ name, mimeType, data }], wireframes: [...] }.
const files = [];
if (fromForm) {
  for (const [key, binary] of Object.entries(item.binary ?? {})) {
    const buffer = await this.helpers.getBinaryDataBuffer(0, key);
    files.push({
      name: binary.fileName ?? key,
      mimeType: binary.mimeType ?? '',
      data: buffer.toString('base64'),
      role: key.startsWith('Wireframes') ? 'wireframe' : 'document',
    });
  }
} else {
  for (const [role, list] of [['document', input.documents], ['wireframe', input.wireframes]]) {
    for (const f of [].concat(list ?? [])) {
      if (f?.data) files.push({ name: f.name ?? 'file', mimeType: f.mimeType ?? '', data: f.data, role });
    }
  }
}
const hasDocuments = files.some((f) => f.role === 'document');
const hasWireframes = files.some((f) => f.role === 'wireframe') || figmaUrls.length > 0;

if (!hasDocuments && !hasWireframes && !jiraKeys.length) {
  throw new Error('Nothing to work from. Upload an FSD or Change Request, add wireframes, or enter Jira story keys.');
}
const usesJira = createInJira || jiraKeys.length > 0;
if (usesJira && (!settings.jiraBaseUrl || settings.jiraBaseUrl.includes('your-site'))) {
  throw new Error('Jira is not set up yet. Open the "Settings" node and enter your Jira site URL, or choose "No" for "Create Jira tickets".');
}
if (createInJira && hasDocuments && !projectKey) {
  throw new Error('Enter the Jira project key where the new stories should be created (for example CPAY).');
}

return [{
  json: {
    channel: fromForm ? 'form' : 'api',
    receivedAt: new Date().toISOString(),
    settings: { ...settings, jiraBaseUrl: settings.jiraBaseUrl.replace(/\/+$/, '') },
    createInJira,
    projectKey,
    jiraKeys,
    figmaUrls,
    // Wireframes alone (no document, no Jira keys) are analysed like a document.
    analyseDocuments: hasDocuments || (hasWireframes && !jiraKeys.length),
    hasDocuments,
    hasWireframes,
    systemName: String(input[fromForm ? 'System name' : 'systemName'] ?? '').trim(),
    testIdPrefix: String(input[fromForm ? 'Test ID prefix' : 'testIdPrefix'] ?? '').trim().toUpperCase().replace(/[^A-Z0-9]/g, ''),
    files,
  },
}];
