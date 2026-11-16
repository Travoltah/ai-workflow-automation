// NODE: "Build reply"  (Code node, mode: Run Once for Each Item)
// A reply is a nested comment: posted under the comment's URN, with parentComment set.
const s = $('Settings').first().json;
const c = $json;
return {
  json: {
    id: c.id,
    url: `${s.linkedinApi}/rest/socialActions/${encodeURIComponent(c.commentUrn)}/comments`,
    body: { actor: c.me, object: c.postUrn, parentComment: c.commentUrn, message: { text: c.reply } },
  },
};
