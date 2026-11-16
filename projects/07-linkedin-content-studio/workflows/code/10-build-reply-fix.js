// NODE: "Build reply fix"  (Code node, mode: Run Once for Each Item)
const s = $('Settings').first().json;
const d = $json;
const problems = d.errors.map((e) => `- ${e.message}${e.excerpt ? ` Here: "${e.excerpt}"` : ''}`).join('\n');
return {
  json: {
    id: d.id,
    anthropicRequest: {
      model: s.model,
      max_tokens: 1000,
      system: 'You edit a short LinkedIn reply so it passes a house style check. Fix only what is listed, keep the meaning and the casual tone. Never use a long dash (— or –).',
      output_config: { effort: 'low', format: { type: 'json_schema', schema: { type: 'object', additionalProperties: false, required: ['reply'], properties: { reply: { type: 'string' } } } } },
      messages: [{ role: 'user', content: `Problems:\n${problems}\n\n<reply>\n${d.reply}\n</reply>` }],
    },
  },
};
