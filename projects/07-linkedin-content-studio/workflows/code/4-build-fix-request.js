// NODE: "Build fix request"  (Code node, mode: Run Once for Each Item)
// Sends the exact problems the style check found, and asks for the smallest rewrite that fixes them.
const s = $('Settings').first().json;
const d = $json;
const article = d.format === 'ARTICLE';
const problems = d.lint.errors.map((e) => `- [${e.part || 'text'}] ${e.message}${e.excerpt ? ` Here: "${e.excerpt}"` : ''}`).join('\n');
const SCHEMA = {
  type: 'object', additionalProperties: false, required: ['title', 'article', 'linkedin_post'],
  properties: { title: { type: 'string' }, article: { type: 'string' }, linkedin_post: { type: 'string' } },
};
return {
  json: {
    id: d.id,
    anthropicRequest: {
      model: s.model,
      max_tokens: article ? 12000 : 4000,
      system: 'You edit drafts so they pass a house style check. Fix only what is listed and keep everything else word for word. Never use a long dash (— or –). Keep the {{LINK}} and {{INFOGRAPHIC}} markers where they are unless a problem is about them.',
      output_config: { effort: 'low', format: { type: 'json_schema', schema: SCHEMA } },
      messages: [{
        role: 'user',
        content: `Problems to fix:\n${problems}\n\n<title>${d.draft.title || ''}</title>\n\n<article>\n${d.draft.body || ''}\n</article>\n\n<linkedin_post>\n${d.draft.linkedinText}\n</linkedin_post>\n\nReturn all three parts.${article ? '' : ' There is no article: return "" for it.'}`,
      }],
    },
  },
};
