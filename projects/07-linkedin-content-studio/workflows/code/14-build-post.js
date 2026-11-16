// NODE: "Build post"  (Code node, mode: Run Once for Each Item)
// Builds the Posts API request once the cover is uploaded. Articles go out as a link card (cover, title,
// description, link to the article on the website); plain posts as an image post.
//
// LinkedIn's "commentary" uses its "little text" format: the characters | { } @ [ ] ( ) < > # \ * _ ~ must be
// escaped with a backslash, or LinkedIn cuts the post short. Hashtags become {hashtag|\#|Tag} templates.
const p = $('Build image upload').item.json;
const start = $('Start image upload').item.json;
const upload = $json; // "Upload cover" (full response)

function littleText(text) {
  return String(text)
    .split(/(#[A-Za-z][A-Za-z0-9_]*)/g)
    .map((part) => (/^#[A-Za-z]/.test(part) ? `{hashtag|\\#|${part.slice(1)}}` : part.replace(/[\\|{}@[\]()<>#*_~]/g, (m) => `\\${m}`)))
    .join('');
}

const image = start?.value?.image;
const uploaded = upload && !upload.error && upload.statusCode >= 200 && upload.statusCode < 300;
if (!image || !uploaded) {
  const why = start?.error ? `starting the upload failed (${String(start.error.message || start.error).slice(0, 200)})` : `uploading the cover failed (${String(upload?.error?.message || upload?.statusCode || 'no response').slice(0, 200)})`;
  return { json: { id: p.id, ready: false, report: { event: 'publish_failed', error: `LinkedIn: ${why}` } } };
}

const content = p.format === 'ARTICLE'
  ? { article: { source: p.articleUrl, thumbnail: image, title: p.title.slice(0, 200), description: p.excerpt.slice(0, 250) } }
  : { media: { id: image, title: p.title.slice(0, 200) } };
const postBody = {
  author: p.me,
  commentary: littleText(p.text),
  visibility: 'PUBLIC',
  distribution: { feedDistribution: 'MAIN_FEED', targetEntities: [], thirdPartyDistributionChannels: [] },
  content,
  lifecycleState: 'PUBLISHED',
  isReshareDisabledByAuthor: false,
};
return { json: { id: p.id, ready: true, postBody } };
