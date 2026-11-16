// NODE: "Build like"  (Code node, mode: Run Once for Each Item)
const s = $('Settings').first().json;
const c = $json;
return {
  json: {
    id: c.id,
    url: `${s.linkedinApi}/rest/reactions?actor=${encodeURIComponent(c.me)}`,
    body: { root: c.commentUrn, reactionType: 'LIKE' },
  },
};
