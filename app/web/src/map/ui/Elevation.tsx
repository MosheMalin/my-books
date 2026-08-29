import { useState } from 'react'

import { useI18n } from '../../lib/i18n'
import { mapText } from '../text'
/**
 * The bookcase, front-on — the SECOND geometry (MAP_PLAN §3.2).
 *
 * Sections stacked as they are built, each divided into columns across and
 * levels down, one cell per shelf. A case built of a low base with a taller
 * unit standing on it is two sections — one piece of furniture on the plan,
 * two grids here (owner, 2026-08-16).
 *
 * ⚠ Sections are stored BOTTOM-FIRST and drawn TOP-FIRST, because furniture
 * stacks upwards and a screen draws downwards. `sectionsTopDown` is the only
 * place that reversal happens.
 *
 * Pinned LTR like the plan and for the same reason: a piece of furniture must
 * not mirror when the UI language changes. *Which physical end column 1 is*
 * stays open — `UI_PLAN` §8 and MAP_PLAN §7 Q3 — so the header says "col 1"
 * and claims nothing more.
 */

import type { Bookcase, Section } from '../core/model'
import { MAX_DEPTH, columnCount, isGap, sectionsTopDown, shelfAt, shelvesDifferingFromDefaultDepth, shelvesInColumns } from '../core/model'
import { nothingBound } from '../cost'
import { whyNotGap } from '../limits'
import type { Selection } from './types'

export type ElevationProps = {
  bc: Bookcase
  selection: Selection
  onSelectShelf: (sectionId: string, col: number, level: number, add: boolean) => void
  /** Switch the marked cells off, or a single hole back on (MAP_PLAN §3.10a). */
  onGaps: (sectionId: string, cells: { col: number; level: number }[], gap: boolean) => void
  onColumnLevels: (sectionId: string, col: number, levels: number) => void
  onColumnCount: (sectionId: string, count: number) => void
  onDefaultLevels: (sectionId: string, n: number) => void
  /** P6.6 — count the shelves in a photo. Optional: a host that does not
   *  offer it renders no control at all (absent, not disabled). */
  onProposeLevels?: ((photo: File) => Promise<number>) | undefined
  onDefaultDepth: (sectionId: string, n: number) => void
  onApplyDefaultLevels: (sectionId: string) => void
  onApplyDefaultDepth: (sectionId: string) => void
  onAddSection: (where: 'top' | 'bottom') => void
  onRemoveSection: (sectionId: string) => void
  /**
   * Swap a section with the one above or below it (P6.7a).
   *
   * ⚠ `direction` is in FURNITURE terms — `up` is towards the ceiling, a
   * higher ordinal. This grid draws TOP-first (`sectionsTopDown`), so the
   * arrow that points up on screen is the one that sends `up` and the two
   * agree only because both ends say so.
   */
  onMoveSection: (sectionId: string, direction: 'up' | 'down') => void
}

/**
 * Count the shelves in one photograph, and offer the number (P6.6).
 *
 * VISION §7's approach B, where it is strongest: `segment.py` already finds
 * horizontal shelf bands, deterministically and for free, so *"the levels of a
 * case can be proposed from one photo of it and confirmed by hand"* (UI_PLAN
 * §3).
 *
 * ⚠ It fills in the field beside it and stops. §3.14 — *the map may propose;
 * only a ✓ binds* — so *apply* is the control that already existed, pressed by
 * a person who has read the number. Nothing here writes, and the photograph is
 * never stored.
 *
 * ⚠ **One is a real answer and says so.** A photo with no horizontal rule
 * across it is a photo of a single shelf, which is what every one of the
 * owner's eleven images is; without that sentence the feature would read as
 * broken on the commonest picture in the library.
 */
function ProposeLevels({ sectionId, label, many, propose, onCount }: {
  sectionId: string
  label: string
  many: boolean
  propose: ((photo: File) => Promise<number>) | undefined
  onCount: (n: number) => void
}) {
  const T = mapText(useI18n().lang)
  const [state, setState] = useState<'idle' | 'busy' | 'failed'>('idle')
  const [said, setSaid] = useState<string>('')
  if (!propose) return null
  return (
    <div className="propose-levels">
      <label className="btn-like">
        <span>{T.propose_levels}</span>
        <input
          type="file"
          accept="image/*"
          aria-label={many ? `${T.propose_levels} — ${label}` : T.propose_levels}
          onChange={(e) => {
            const photo = e.target.files?.[0]
            // ⚠ Cleared straight away, so choosing the SAME file twice fires
            // again — a file input does not raise `change` for an unchanged
            // value, and "nothing happened" after a retry reads as a dead
            // control.
            e.target.value = ''
            if (!photo) return
            setState('busy')
            setSaid('')
            void propose(photo)
              .then((n) => {
                setState('idle')
                setSaid(T.proposed_levels(n))
                if (n > 1) onCount(n)
              })
              .catch(() => setState('failed'))
          }}
        />
      </label>
      <p className="note" id={`propose-${sectionId}`}>
        {state === 'busy' ? T.proposing_levels
          : state === 'failed' ? T.propose_failed
            : said || T.propose_levels_hint}
      </p>
    </div>
  )
}

export function Elevation(props: ElevationProps) {
  const T = mapText(useI18n().lang)
  const { bc } = props
  const many = bc.sections.length > 1
  return (
    <div className="elevation" dir="ltr">
      {many && (
        <button
          type="button"
          className="section-add"
          onClick={() => props.onAddSection('top')}
          aria-label={T.add_section_top}
        >
          {T.add_section_top_long}
        </button>
      )}

      {sectionsTopDown(bc).map((sec) => (
        <SectionBlock key={sec.id} {...props} sec={sec} many={many} />
      ))}

      <button
        type="button"
        className="section-add"
        onClick={() => props.onAddSection(many ? 'bottom' : 'top')}
        aria-label={many ? T.add_section_under : T.split_sections}
      >
        {many ? T.add_section_under_long : T.split_sections_long}
      </button>
    </div>
  )
}

function SectionBlock({
  bc,
  sec,
  many,
  selection,
  ...props
}: ElevationProps & { sec: Section; many: boolean }) {
  const T = mapText(useI18n().lang)
  const cols = columnCount(sec)
  // The cells marked in THIS section. A set, since P6.3.2b: a television is
  // a rectangle of cells and the owner marks them before pressing delete.
  const marked = selection.cells.filter(
    (c) => c.caseId === bc.id && c.sectionId === sec.id)
  const blocked = marked.length > 0 ? whyNotGap(sec, marked) : null
  // ⚠ The touch path for marking a SET. `onClick`'s `ctrlKey`/`shiftKey` are
  // desktop-only — a review measured that a finger carries none of them, so
  // the set could never exceed one cell on a phone and the item's whole
  // premise ("a television is a rectangle of cells") was a desktop feature.
  // A latch is one control, it is absent until a cell is marked, and it says
  // its own rule rather than hiding a modifier nothing mentions.
  const [adding, setAdding] = useState(false)
  const index = bc.sections.findIndex((s) => s.id === sec.id)
  // Numbered BOTTOM-UP, because that is how the thing was built: section 1
  // stands on the floor.
  const label = T.section_n(index + 1)
  const where =
    index === 0 ? T.section_on_floor : index === bc.sections.length - 1 ? T.section_on_top : ''
  // Accessible names print the section only when there IS more than one — the
  // same "only what discriminates" rule the shelf address follows. Uniqueness
  // is not at risk: with one section there is nothing to collide with.
  const addr = many ? `${label}, ` : ''
  const differing = shelvesDifferingFromDefaultDepth(sec)

  return (
    <section className="elev-section">
      {many && (
        <header className="section-head">
          <span className="section-name">
            {label}
            <span className="section-where">{where}</span>
          </span>
          {/* ⚠ ABSENT at the ends of the stack, not disabled — the house
              rule, and here it is also the only thing that keeps the two
              directions honest: the server answers 409 for a neighbour that
              is not there, and a disabled button would invite the press
              that earns it. Each arrow carries the SECTION's name, because
              two sections both announcing "move up" collide. */}
          {index < bc.sections.length - 1 && (
            <button
              type="button"
              className="section-move"
              aria-label={T.move_section_up(label)}
              title={T.move_section_up(label)}
              onClick={() => props.onMoveSection(sec.id, 'up')}
            >
              ▲
            </button>
          )}
          {index > 0 && (
            <button
              type="button"
              className="section-move"
              aria-label={T.move_section_down(label)}
              title={T.move_section_down(label)}
              onClick={() => props.onMoveSection(sec.id, 'down')}
            >
              ▼
            </button>
          )}
          <button
            type="button"
            className="danger"
            aria-label={T.remove_section(label)}
            title={T.remove_section_title(label, sec.shelves.length)}
            onClick={() => {
              // ⚠ Asked only when something stands here. Every slot of an
              // untouched section holds nothing, and a dialog in front of a
              // gesture that destroys nothing is what teaches people to click
              // through the ones that do (owner, drawing with it).
              if (nothingBound(sec.shelves)
                  || confirm(T.remove_section_confirm(label, sec.shelves.length))) {
                props.onRemoveSection(sec.id)
              }
            }}
          >
            ✕
          </button>
        </header>
      )}

      {/* ABSENT until cells are marked, not disabled — the house rule. It is
          the only destructive control in the elevation that acts on a set, so
          it says how many, and it never mentions the bookcase: deleting cells
          does not delete furniture (owner, 2026-08-22). */}
      {marked.length > 0 && (
        <div className="elev-marked" role="group">
          {/* ⚠ `.rtl-safe` on every counted sentence. A review measured these
              in the LTR-pinned elevation: a string BEGINNING with a digit has
              no strong first character, so `2 תאים מסומנים` rendered with the
              2 at the far left — the end of the phrase for a Hebrew reader —
              and the refusal's full stop landed before its first word.
              `unicode-bidi: plaintext` takes the direction from the first
              STRONG character, which is the Hebrew, and resolves it right.
              The group carried this same text as an `aria-label` too, so a
              screen reader said it twice; the visible text is enough. */}
          <span className="note rtl-safe">{T.marked_cells(marked.length)}</span>
          {/* ⚠ The reason INSTEAD of the button, not a disabled button beside
              it. The server refuses these with a 409 in English, after the
              press; MapScreen's rule is that a refusal the screen could have
              stated belongs before it. The 409 remains the backstop for what
              another tab did — and for a NAMED empty cell, which the document
              cannot see. */}
          <button
            type="button"
            className={`latch${adding ? ' on' : ''}`}
            aria-pressed={adding}
            title={T.adding_more_cells}
            onClick={() => setAdding((on) => !on)}
          >
            {T.add_more_cells}
          </button>
          {blocked ? (
            // Named per CAUSE, and each names a remedy that EXISTS. A review
            // pressed this on a cell that was empty but two rows deep and was
            // told to "clear it first" — of nothing.
            <span className="note warn rtl-safe" role="status">
              {blocked.books > 0
                ? T.cells_have_books(blocked.books)
                : blocked.photos > 0
                  ? T.cells_have_photos(blocked.photos)
                  : T.cells_are_deep(blocked.deeper)}
            </span>
          ) : (
            <button
              type="button"
              className="danger"
              title={T.make_space_title}
              onClick={() =>
                props.onGaps(sec.id, marked.map((c) => ({ col: c.col, level: c.level })), true)}
            >
              {T.make_space(marked.length)}
            </button>
          )}
        </div>
      )}

      {/* ⚠ On screen, not in a `title`. The hole's own explanation lived in a
          hover tooltip, which a phone never shows — and the phone is the
          device this is catalogued from. One line, only while the section
          has a hole, saying the one thing that is not discoverable. */}
      {sec.gaps.length > 0 && (
        <p className="note rtl-safe elev-gap-hint">{T.gaps_are_tappable}</p>
      )}

      {/* The scroll lives HERE, around one section's columns — not around the
          whole panel (owner, 2026-08-16). A wide bookcase should slide its own
          columns; it should not drag the name box and the depth rule sideways
          with them. */}
      <div className="elev-scroll">
        <div
          className="elevation-grid"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(44px, 1fr))` }}
        >
        {Array.from({ length: cols }, (_, col) => (
          <div className="elev-col" key={col}>
            <div className="elev-col-head">{T.col_head(col + 1)}</div>
            {Array.from({ length: sec.columnLevels[col] ?? 0 }, (_, level) => {
              const shelf = shelfAt(sec, col, level)
              const gap = isGap(sec, col, level)
              const isSel = marked.some((c) => c.col === col && c.level === level)
              const override = shelf ? shelf.depth !== sec.defaultDepth : false
              // ⚠ A hole is still a BUTTON, and it is the only way back: the
              // owner's own words, *"user should be able to click on a
              // 'missing' cell and make it a real shelf again"*. It says what
              // it will do, not what it is, because "gap" names a state and
              // an accessible name has to name an action.
              if (gap) {
                return (
                  <button
                    key={level}
                    type="button"
                    className="elev-cell gap"
                    aria-label={T.restore_cell(addr, col + 1, level + 1)}
                    title={T.restore_cell_title}
                    onClick={() => props.onGaps(sec.id, [{ col, level }], false)}
                  >
                    {/* ⚠ Not `.elev-level`: that class dims to 0.7, and a
                        review measured the hole's number at 1.7–2.1:1 against
                        the panel — under the 4.5:1 floor, effectively blank in
                        the light theme. A hole is the ONLY way back, and its
                        every other affordance (a `title`, a `:hover`) is
                        invisible to the device this is catalogued from. So it
                        is drawn as DIFFERENT ink, not less: the number at full
                        strength, and a glyph that says something can be done
                        here. */}
                    <span className="elev-level gap-level">{level + 1}</span>
                    <span className="gap-mark" aria-hidden="true">+</span>
                  </button>
                )
              }
              // ⚠ A cell the SERVER says holds no shelf is drawn and named
              // differently. A review measured the two at 375×812 immediately
              // after a real unbind: identical markup, identical computed
              // background, border, colour and opacity — and on the owner's
              // library every addressed shelf holds zero books and zero
              // photographs, so the badges that might have differed do not
              // exist. The grid changed by ZERO pixels for the gesture the
              // owner had just made, and the accessible name still said
              // *shelf*. The gap branch above does the opposite for the same
              // reason, and this is that treatment, one state along.
              const free = shelf?.free === true
              return (
                <button
                  key={level}
                  type="button"
                  className={`elev-cell${isSel ? ' selected' : ''}${override ? ' override' : ''}${free ? ' empty' : ''}`}
                  aria-label={free
                    ? T.empty_cell(addr, col + 1, level + 1)
                    : T.shelf_at(addr, col + 1, level + 1)}
                  aria-pressed={isSel}
                  // Ctrl/Shift adds to the marked set — the same modifier the
                  // plan already uses to select several rooms, so the gesture
                  // is learned once.
                  onClick={(e) =>
                    props.onSelectShelf(sec.id, col, level,
                      adding || e.ctrlKey || e.metaKey || e.shiftKey)}
                >
                  <span className="elev-level">{level + 1}</span>
                  {free && <span className="empty-mark" aria-hidden="true">·</span>}
                  {shelf && shelf.depth > 1 && (
                    <span className="elev-depth" title={T.rows_deep(shelf.depth)}>
                      ×{shelf.depth}
                    </span>
                  )}
                  {shelf && shelf.photos > 0 && <span className="elev-photos">{shelf.photos}📷</span>}
                  {/* ⚠ `books` was on `Shelf` and rendered nowhere, so a
                      refusal naming a cell with books pointed at a cell
                      carrying no marker at all — nothing on the grid to
                      look for. */}
                  {shelf && shelf.books > 0 && (
                    <span className="elev-books" title={T.marked_cells(shelf.books)}>
                      {shelf.books}
                    </span>
                  )}
                </button>
              )
            })}
            <div className="elev-col-foot">
              <button
                type="button"
                aria-label={T.remove_level(addr, col + 1)}
                disabled={(sec.columnLevels[col] ?? 1) <= 1}
                onClick={() => props.onColumnLevels(sec.id, col, (sec.columnLevels[col] ?? 1) - 1)}
              >
                −
              </button>
              <button
                type="button"
                aria-label={T.add_level(addr, col + 1)}
                onClick={() => props.onColumnLevels(sec.id, col, (sec.columnLevels[col] ?? 1) + 1)}
              >
                +
              </button>
            </div>
            </div>
          ))}
        </div>
      </div>

      <div className="elevation-cols">
        <button
          type="button"
          aria-label={many ? T.remove_column_of(label) : T.remove_column}
          disabled={cols <= 1}
          onClick={() => {
            // The slots in the column about to go — how many, and whether
            // any of them holds a photograph or a book.
            const going = sec.shelves.filter((s) => s.col >= cols - 1)
            const losing = shelvesInColumns(sec, cols - 1)
            if (!nothingBound(going) && !confirm(T.remove_column_confirm(losing)))
              return
            props.onColumnCount(sec.id, cols - 1)
          }}
        >
          − {T.column}
        </button>
        <button
          type="button"
          aria-label={many ? T.add_column_of(label) : T.add_column}
          onClick={() => props.onColumnCount(sec.id, cols + 1)}
        >
          + {T.column}
        </button>
      </div>

      <div className="section-defaults">
        <label>
          <span>{T.new_levels}</span>
          <input
            type="number"
            min={1}
            max={12}
            value={sec.defaultLevels}
            aria-label={many ? T.default_levels_of(label) : T.default_levels}
            onChange={(e) => props.onDefaultLevels(sec.id, Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          aria-label={many ? T.apply_levels_of(label) : T.apply_levels}
          onClick={() => props.onApplyDefaultLevels(sec.id)}
        >
          {T.apply}
        </button>
        <ProposeLevels sectionId={sec.id} label={label} many={many}
                       propose={props.onProposeLevels}
                       onCount={(n) => props.onDefaultLevels(sec.id, n)} />
        <label>
          <span>{T.new_depth}</span>
          <input
            type="number"
            min={1}
            max={MAX_DEPTH}
            value={sec.defaultDepth}
            aria-label={many ? T.default_depth_of(label) : T.default_depth}
            onChange={(e) => props.onDefaultDepth(sec.id, Number(e.target.value))}
          />
        </label>
      </div>

      {differing > 0 && (
        <p className="rule">
          {T.depth_kept(differing, label)}
          <button
            type="button"
            aria-label={many ? T.apply_depth_of(label) : T.apply_depth}
            onClick={() => props.onApplyDefaultDepth(sec.id)}
          >
            {T.apply_to_all(sec.shelves.length)}
          </button>
        </p>
      )}
    </section>
  )
}
