// Fake data for the UI mock. Shapes deliberately mirror VISION.md §5.2/§5.3/§5.7
// (Book / Copy / Shelf+depth / PhysicalLibrary) so the mock exercises the real model.

// A place holds bookcases directly (no room level — owner's call, 2026-08-07):
// "work room" is simply another bookcase entry inside Home, added with the +.
// `rooms` are sketch outlines only — labels on the plan, not a data level.
export const physicalLibraries = [
  { id: 'pl1', name: { he: 'הבית', en: 'Home' }, sketch: true, rooms: [
      { label: { he: 'סלון', en: 'Living room' },  x: 3,  y: 3,  w: 54, h: 34 },
      { label: { he: 'חדר עבודה', en: 'Study' },   x: 60, y: 3,  w: 37, h: 24 },
      { label: { he: 'מסדרון', en: 'Hallway' },    x: 60, y: 29, w: 37, h: 8 },
    ] },
  { id: 'pl2', name: { he: 'המשרד', en: 'Office' }, sketch: true, rooms: [
      { label: { he: 'החדר שלי', en: 'My room' }, x: 6, y: 4, w: 60, h: 30 },
    ] },
  { id: 'pl3', name: { he: 'אצל ההורים', en: "Parents'" }, sketch: false, rooms: [] },
];

// `plan` places the case on its place's sketch (same 0-100 × 0-46 coordinates).
// `columns` = vertical bays. A shelf's address inside a case is (column, level);
// see the shelves table. Column is an ATTRIBUTE of the shelf's position, for the
// same reason VISION §5.7 makes depth one: splitting a case into one Bookcase
// per bay would put two records in one physical slot on the map.
export const bookcases = [
  { id: 'bc1', plId: 'pl1', columns: 2, name: { he: 'ארון הסלון', en: 'Living room case' }, plan: { x: 8,  y: 5, w: 26, h: 3.5 } },
  { id: 'bc2', plId: 'pl1', columns: 1, name: { he: 'ארון חדר העבודה', en: 'Study case' },  plan: { x: 63, y: 5, w: 3.5, h: 10 } },
  { id: 'bc3', plId: 'pl2', columns: 1, name: { he: 'מדף המשרד', en: 'Office shelf' },      plan: { x: 12, y: 7, w: 18, h: 3.5 } },
  { id: 'bc4', plId: 'pl3', columns: 1, name: { he: 'הארון הישן', en: 'The old case' },     plan: null },
];

// A shelf's address inside a case is (col, level) — col = which vertical bay,
// level = which shelf down from the top. depthCount = rows front-to-back
// (VISION §5.7); depthRead = which depths were ever read. Three axes, three
// distinct words: COLUMN across, LEVEL down, DEPTH back. Never "row" or "band"
// for any of them — `segment.py` already owns "band" for something else.
export const shelves = [
  { id: 'sh1', bcId: 'bc1', col: 1, level: 1, depthCount: 1, photo: 'assets/shelves/shelf1.jpg', lastRead: '2026-08-05', depthRead: [1] },
  { id: 'sh2', bcId: 'bc1', col: 1, level: 2, depthCount: 2, photo: 'assets/shelves/shelf2.jpg', lastRead: '2026-08-06', depthRead: [1, 2] },
  { id: 'sh3', bcId: 'bc1', col: 1, level: 3, depthCount: 3, photo: 'assets/shelves/shelf3.jpg', lastRead: '2026-03-11', depthRead: [1] },
  { id: 'sh8', bcId: 'bc1', col: 2, level: 1, depthCount: 1, photo: 'assets/shelves/shelf6.jpg', lastRead: '2026-08-06', depthRead: [1] },
  { id: 'sh9', bcId: 'bc1', col: 2, level: 2, depthCount: 1, photo: null,                        lastRead: null,         depthRead: [] },
  { id: 'sh4', bcId: 'bc2', col: 1, level: 1, depthCount: 1, photo: 'assets/shelves/shelf4.jpg', lastRead: '2026-08-06', depthRead: [1] },
  { id: 'sh5', bcId: 'bc2', col: 1, level: 2, depthCount: 2, photo: 'assets/shelves/shelf5.jpg', lastRead: null,         depthRead: [] },
  { id: 'sh6', bcId: 'bc3', col: 1, level: 1, depthCount: 1, photo: 'assets/shelves/shelf6.jpg', lastRead: '2026-07-28', depthRead: [1] },
  { id: 'sh7', bcId: 'bc4', col: 1, level: 1, depthCount: 1, photo: null,                        lastRead: null,         depthRead: [] },
  // A wishlist is modelled as a VIRTUAL shelf (owner's call, 2026-08-07): no
  // bookcase, no photo, never read. Books on it are excluded from "what I own"
  // unless the wishlist filter is on.
  { id: 'shWish', bcId: null, virtual: true, name: { he: 'רשימת משאלות', en: 'Wishlist' }, depthCount: 1, photo: null, lastRead: null, depthRead: [] },
];

// Read history per shelf — the ONLY place a "run" surfaces in normal use (VISION §5.5).
export const reads = [
  { id: 'rd7', shelfId: 'sh2', depth: 2, at: '2026-08-06 14:22', added: 9,  corrected: 0, unchanged: 0,  unseen: 0, mode: 'llmpage', runNo: 17 },
  { id: 'rd6', shelfId: 'sh4', depth: 1, at: '2026-08-06 11:05', added: 2,  corrected: 3, unchanged: 12, unseen: 1, mode: 'llmpage', runNo: 16 },
  { id: 'rd8', shelfId: 'sh8', depth: 1, at: '2026-08-06 10:40', added: 3,  corrected: 0, unchanged: 0,  unseen: 0, mode: 'llmpage', runNo: 16 },
  { id: 'rd5', shelfId: 'sh1', depth: 1, at: '2026-08-05 22:40', added: 0,  corrected: 1, unchanged: 14, unseen: 2, mode: 'llmpage', runNo: 15 },
  { id: 'rd4', shelfId: 'sh2', depth: 1, at: '2026-08-05 21:12', added: 3,  corrected: 1, unchanged: 11, unseen: 0, mode: 'llmpage', runNo: 15 },
  { id: 'rd3', shelfId: 'sh6', depth: 1, at: '2026-07-28 09:30', added: 7,  corrected: 0, unchanged: 0,  unseen: 0, mode: 'fullpage', runNo: 12 },
  { id: 'rd2', shelfId: 'sh1', depth: 1, at: '2026-06-02 18:00', added: 14, corrected: 2, unchanged: 0,  unseen: 0, mode: 'spines',  runNo: 8 },
  { id: 'rd1', shelfId: 'sh3', depth: 1, at: '2026-03-11 16:45', added: 11, corrected: 0, unchanged: 0,  unseen: 0, mode: 'spines',  runNo: 5 },
];

// [title, author, status, shelfId, depth, addedAt, spineIdx, lentTo|null, rating|0, readStatus]
const RAW = [
  ['היער השיכור', "ג'ראלד דארל", 'approved', 'sh1', 1, '2026-06-02', 0, null, 4, 'read'],
  ['פגישות עם בעלי חיים', "ג'ראלד דארל", 'approved', 'sh1', 1, '2026-06-02', 1, null, 5, 'read'],
  ['את כולם ברא', "ג'ראלד דארל", 'auto', 'sh1', 1, '2026-06-02', 2, null, 0, 'unread'],
  ['הפיקניק ומהומות אחרות', "ג'ראלד דארל", 'approved', 'sh1', 1, '2026-06-02', 3, 'דנה', 4, 'read'],
  ['ציפור הלעג', "ג'ראלד דארל", 'auto', 'sh1', 1, '2026-06-02', 4, null, 0, 'unread'],
  ['משפחתי וחיות אחרות', "ג'ראלד דארל", 'approved', 'sh1', 1, '2026-06-02', 5, null, 5, 'read'],
  ['ציפורים חיות וקרובים', "ג'ראלד דארל", 'auto', 'sh1', 1, '2026-06-02', 6, null, 0, 'unread'],
  ['גן האלים', "ג'ראלד דארל", 'approved', 'sh1', 1, '2026-06-02', 7, null, 3, 'reading'],
  ['הדברים מבהיקים', 'ג׳יימס הריוט', 'approved', 'sh8', 1, '2026-06-02', 8, null, 4, 'read'],
  ['אם רק יכלו לדבר', 'ג׳יימס הריוט', 'auto', 'sh8', 1, '2026-08-05', 9, null, 0, 'unread'],
  ['The Elephant', 'Peter Matthiessen', 'manual', 'sh8', 1, '2026-06-02', 10, null, 0, 'unread'],
  ['משחקי הכס', "ג'ורג' ר.ר. מרטין", 'approved', 'sh2', 1, '2026-08-05', 11, null, 5, 'read'],
  ['עימות המלכים', "ג'ורג' ר.ר. מרטין", 'approved', 'sh2', 1, '2026-08-05', 12, null, 4, 'read'],
  ['סופה של חרבות', "ג'ורג' ר.ר. מרטין", 'auto', 'sh2', 1, '2026-08-05', 13, null, 0, 'unread'],
  ['משתה לעורבים', "ג'ורג' ר.ר. מרטין", 'auto', 'sh2', 1, '2026-08-05', 14, null, 0, 'unread'],
  ['מלכי הכופרים', 'סטיבן אריקסון', 'approved', 'sh2', 1, '2026-08-05', 15, null, 4, 'reading'],
  ['ספינות מן המערב', 'סטיבן אריקסון', 'approved', 'sh2', 1, '2026-08-05', 16, null, 0, 'unread'],
  ['המסע של הוקווד', 'סטיבן אריקסון', 'auto', 'sh2', 1, '2026-08-05', 17, null, 0, 'unread'],
  ['עיר הזמן', 'גיא גבריאל קיי', 'approved', 'sh2', 1, '2026-08-05', 18, 'יואב', 5, 'read'],
  ['הפסיפס הסרנטיני', 'גיא גבריאל קיי', 'approved', 'sh2', 1, '2026-08-05', 19, null, 4, 'read'],
  ['שם הרוח', 'פטריק רות׳פוס', 'approved', 'sh2', 2, '2026-08-06', 0, null, 5, 'read'],
  ['פחדו של אדם חכם', 'פטריק רות׳פוס', 'approved', 'sh2', 2, '2026-08-06', 1, null, 4, 'read'],
  ['הצל האחרון', 'ברנדון סנדרסון', 'auto', 'sh2', 2, '2026-08-06', 2, null, 0, 'unread'],
  ['בני הערפל', 'ברנדון סנדרסון', 'approved', 'sh2', 2, '2026-08-06', 3, null, 5, 'read'],
  ['הבאר העולה', 'ברנדון סנדרסון', 'approved', 'sh2', 2, '2026-08-06', 4, null, 4, 'read'],
  ['גיבור הדורות', 'ברנדון סנדרסון', 'auto', 'sh2', 2, '2026-08-06', 5, null, 0, 'unread'],
  ['דרך המלכים', 'ברנדון סנדרסון', 'approved', 'sh2', 2, '2026-08-06', 6, null, 5, 'reading'],
  ['מילות זוהר', 'ברנדון סנדרסון', 'auto', 'sh2', 2, '2026-08-06', 7, null, 0, 'unread'],
  ['אלנטריס', 'ברנדון סנדרסון', 'manual', 'sh2', 2, '2026-08-06', 8, null, 0, 'unread'],
  ["הצ'ופצ'יק של הקומקום", 'דן שפירא', 'approved', 'sh3', 1, '2026-03-11', 9, null, 3, 'read'],
  ['אומת הסטארטאפ', 'דן סנור ושאול זינגר', 'approved', 'sh3', 1, '2026-03-11', 10, null, 4, 'read'],
  ['הנבונים', 'עמוס עוז', 'approved', 'sh3', 1, '2026-03-11', 11, null, 5, 'read'],
  ['מיכאל שלי', 'עמוס עוז', 'approved', 'sh3', 1, '2026-03-11', 12, null, 4, 'read'],
  ['סיפור על אהבה וחושך', 'עמוס עוז', 'approved', 'sh3', 1, '2026-03-11', 13, 'מיכל', 5, 'read'],
  ['קופסה שחורה', 'עמוס עוז', 'auto', 'sh3', 1, '2026-03-11', 14, null, 0, 'unread'],
  ['החיה שבקרבי', 'דויד גרוסמן', 'approved', 'sh3', 1, '2026-03-11', 15, null, 4, 'read'],
  ['עיין ערך אהבה', 'דויד גרוסמן', 'approved', 'sh3', 1, '2026-03-11', 16, null, 5, 'read'],
  ['סוס אחד נכנס לבר', 'דויד גרוסמן', 'approved', 'sh4', 1, '2026-08-06', 17, null, 4, 'read'],
  ['אישה בורחת מבשורה', 'דויד גרוסמן', 'auto', 'sh4', 1, '2026-08-06', 18, null, 0, 'unread'],
  ['ציפורי', 'אהרן אפלפלד', 'manual', 'sh4', 1, '2026-08-06', 19, null, 0, 'unread'],
  ['הכל זורם', 'ואסילי גרוסמן', 'approved', 'sh4', 1, '2026-08-06', 0, null, 5, 'read'],
  ['חיים ואדם', 'ואסילי גרוסמן', 'auto', 'sh4', 1, '2026-08-06', 1, null, 0, 'unread'],
  ['הגשר על נהר הדרינה', 'איוו אנדריץ׳', 'approved', 'sh6', 1, '2026-07-28', 2, null, 4, 'read'],
  ['מאה שנים של בדידות', 'גבריאל גארסיה מארקס', 'approved', 'sh6', 1, '2026-07-28', 3, null, 5, 'read'],
  ['אהבה בימי כולרה', 'גבריאל גארסיה מארקס', 'approved', 'sh6', 1, '2026-07-28', 4, null, 4, 'read'],
  ['הזקן והים', 'ארנסט המינגוויי', 'approved', 'sh6', 1, '2026-07-28', 5, null, 4, 'read'],
  ['ולמי אשר צלצלו הפעמונים', 'ארנסט המינגוויי', 'auto', 'sh6', 1, '2026-07-28', 6, null, 0, 'unread'],
  ['Sapiens', 'Yuval Noah Harari', 'approved', 'sh6', 1, '2026-07-28', 7, null, 5, 'read'],
  ['1984', 'George Orwell', 'approved', 'sh6', 1, '2026-07-28', 8, null, 5, 'read'],
  ['חוות החיות', 'ג׳ורג׳ אורוול', 'approved', 'sh6', 1, '2026-07-28', 9, null, 4, 'read'],
];

export const books = RAW.map(([title, author, status, shelfId, depth, addedAt, si, lentTo, rating, readStatus], i) => ({
  id: 'b' + (i + 1),
  title, author, status, addedAt,
  spine: `assets/spines/s${String(si % 20).padStart(2, '0')}.jpg`,
  work: { rating, notes: '', readStatus },
  copies: [{
    id: `b${i + 1}c1`, label: '', shelfId, depth,
    tags: [], lastSeen: addedAt,
    lending: lentTo ? { lentTo, lentAt: '2026-05-14', dueAt: '2026-09-01' } : null,
    provenance: [{ readId: 'rd5', shelfId, depth, at: addedAt }],
  }],
  unseenReads: 0,
}));

// One book deliberately owned twice, to exercise the copy UI (VISION §5.1).
books.find(b => b.title === 'הזקן והים').copies.push({
  id: 'bx-c2', label: 'כריכה רכה', shelfId: 'sh4', depth: 1, tags: ['שאול'],
  lastSeen: '2026-08-06', lending: null, provenance: [],
});
// One book not seen in the last reads of its shelf (VISION §5.6 soft prompt).
books.find(b => b.title === 'ציפור הלעג').unseenReads = 3;

// Two skipped copy-resolution questions, waiting in the "duplicates" filter
// (VISION §5.4 — skipped questions accumulate, they are never lost).
books.find(b => b.title === 'הזקן והים').dupPending = { shelfId: 'sh4', depth: 1 };
books.find(b => b.title === 'הנבונים').dupPending = { shelfId: 'sh6', depth: 1 };

// A few wishlist entries — books wanted, not owned.
[['הדרך', 'קורמאק מקארתי'], ['שמש אחרת', 'אוקטביה באטלר'], ['פירנצה', 'רוס קינג']]
  .forEach(([title, author], i) => books.push({
    id: 'w' + (i + 1), title, author, status: 'manual', addedAt: '2026-08-04',
    spine: 'assets/spines/s12.jpg', work: { rating: 0, notes: '', readStatus: 'unread' },
    unseenReads: 0,
    copies: [{ id: 'w' + (i + 1) + 'c1', label: '', shelfId: 'shWish', depth: 1, tags: [], lastSeen: null, lending: null, provenance: [] }],
  }));

// ---- Capture tab: photos waiting to be processed / just processed -------------
export const captures = [
  { id: 'cap1', file: 'IMG_8131.jpeg', thumb: 'assets/shelves/shelf3.jpg', shelfId: 'sh5', depth: 1, order: 1, state: 'ready' },
  { id: 'cap2', file: 'IMG_8132.jpeg', thumb: 'assets/shelves/shelf4.jpg', shelfId: 'sh5', depth: 2, order: 1, state: 'ready' },
  { id: 'cap3', file: 'IMG_8133.jpeg', thumb: 'assets/shelves/shelf6.jpg', shelfId: null,  depth: 1, order: 1, state: 'unassigned' },
  { id: 'cap4', file: 'IMG_8134.jpeg', thumb: 'assets/shelves/shelf1.jpg', shelfId: 'sh1', depth: 1, order: 1, state: 'done' },
];

// Inline review rows produced by the most recent read (VISION §5.6 diff + §5.4 dup prompt).
export const reviewRows = [
  { id: 'r1', spine: 'assets/spines/s00.jpg', title: 'שם הרוח', author: 'פטריק רות׳פוס', tier: 'AUTO', score: 91, ocr: 'שם הרוח פטריק רותפוס', diff: 'added' },
  { id: 'r2', spine: 'assets/spines/s01.jpg', title: 'פחדו של אדם חכם', author: 'פטריק רות׳פוס', tier: 'AUTO', score: 88, ocr: 'פחדו של אדם חכם', diff: 'added' },
  { id: 'r3', spine: 'assets/spines/s02.jpg', title: 'הצל האחרון', author: 'ברנדון סנדרסון', tier: 'REVIEW', score: 61, ocr: 'הצל האחדון סנדדסון', diff: 'added',
    alts: [['הצל האחרון', 'ברנדון סנדרסון', 61], ['הצללים הארוכים', 'ברנדון סנדרסון', 54], ['צל של ספק', 'ג׳ון גרישם', 49]] },
  { id: 'r4', spine: 'assets/spines/s03.jpg', title: 'בני הערפל', author: 'ברנדון סנדרסון', tier: 'AUTO', score: 84, ocr: 'בני הערפל', diff: 'unchanged' },
  { id: 'r5', spine: 'assets/spines/s04.jpg', title: 'הזקן והים', author: 'ארנסט המינגוויי', tier: 'REVIEW', score: 72, ocr: 'הזקן והים המינגוויי', diff: 'duplicate',
    dupOf: { shelf: 'sh6', label: { he: 'הבית · ארון הסלון · מדף יחיד', en: 'Home · Living room case · The one shelf' } } },
  { id: 'r6', spine: 'assets/spines/s05.jpg', title: 'גיבור הדורות', author: 'ברנדון סנדרסון', tier: 'REVIEW', score: 58, ocr: 'גיבוד הדודות', diff: 'added',
    alts: [['גיבור הדורות', 'ברנדון סנדרסון', 58], ['גיבורי הדור', 'לא ידוע', 51]] },
  { id: 'r7', spine: 'assets/spines/s06.jpg', title: null, author: null, tier: 'none', score: 0, ocr: 'ןכהןכנות אחרות', diff: 'unmatched' },
  { id: 'r8', spine: 'assets/spines/s07.jpg', title: null, author: null, tier: 'none', score: 0, ocr: '', diff: 'unmatched' },
];

export const byId = Object.fromEntries(books.map(b => [b.id, b]));
export const shelfById = Object.fromEntries(shelves.map(s => [s.id, s]));
export const bcById = Object.fromEntries(bookcases.map(b => [b.id, b]));
export const plById = Object.fromEntries(physicalLibraries.map(p => [p.id, p]));
