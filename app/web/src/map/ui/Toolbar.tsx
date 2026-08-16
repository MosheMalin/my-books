import { useI18n } from '../../lib/i18n'
import { mapText, type MapText } from '../text'
/**
 * The toolbar: four menus, four icons, and the storey.
 *
 * It used to be fifteen buttons on one line (owner, 2026-08-16: *"way too many
 * buttons on the control line"*). The rule that shrank it: **a command lives
 * in a menu; only the tools get a permanent button**, because a tool is what
 * you switch between while drawing and everything else is something you do
 * once. The icons carry tooltips rather than labels for the same reason.
 */

import { useRef } from 'react'

import type { Underlay } from '../core/model'
import { ArrowIcon, CaseIcon, PanIcon, RoomIcon } from './icons'
import { Menu } from './Menu'
import type { Theme, Tool } from './types'

type Props = {
  tool: Tool
  theme: Theme
  ghosts: boolean
  allFloors: boolean
  manyFloors: boolean
  /** True while the read-only overview is up: nothing can be drawn, so the
   *  tools say so rather than looking available and doing nothing. */
  readOnly: boolean
  saved: 'saving' | 'saved' | 'failed'
  underlay: Underlay | null
  canUndo: boolean
  canRedo: boolean
  canPaste: boolean
  selectedCount: number
  onTool: (t: Tool) => void
  onTheme: (t: Theme) => void
  onGhosts: (on: boolean) => void
  onAllFloors: (on: boolean) => void
  onUndo: () => void
  onRedo: () => void
  onFit: () => void
  onZoom: (factor: number) => void
  onCopy: () => void
  onPaste: () => void
  onDelete: () => void
  onReload: () => void
  onUnderlay: (file: File) => void
  onUnderlayChange: (patch: Partial<Underlay>) => void
  onUnderlayClear: () => void
}

/**
 * The four tools, as drawn icons. `auto` is the arrow and it is the default: it
 * guesses from where you press, and the other two are how you overrule it.
 *
 * ⚠ No key numbers in the tooltips (owner, 2026-08-16). They still work; a
 * tooltip is for what the control DOES, and "(2)" was the same meaningless
 * digit that got the labels rewritten two passes ago.
 */
const tools = (T: MapText): { tool: Tool; icon: () => React.ReactElement; label: string; hint: string }[] => [
  {
    tool: 'auto',
    icon: ArrowIcon,
    label: T.arrow,
    hint: T.hint_arrow, // from where you press: a room’s border moves it, inside a room draws a bookcase, outside every room draws a room. Ctrl+drag selects several.',
  },
  {
    tool: 'room',
    icon: RoomIcon,
    label: T.draw_room,
    hint: T.hint_room, // draws a room, wherever you start.',
  },
  {
    tool: 'case',
    icon: CaseIcon,
    label: T.draw_case,
    hint: T.hint_case, // draws a bookcase, wherever you start.',
  },
  {
    tool: 'pan',
    icon: PanIcon,
    label: T.pan,
    hint: T.hint_pan, // the plan. So do the middle button and two fingers.',
  },
]

const savedText = (T: MapText) => ({
  saving: T.saving,
  saved: T.saved,
  // ⚠ The lab said "use File ▸ Save to file" here, because browser storage
  // was all it had. The plan lives in the library now, so the honest advice
  // is to try again.
  failed: T.save_failed,
})

export function Toolbar(props: Props) {
  const T = mapText(useI18n().lang)
  const underlayRef = useRef<HTMLInputElement | null>(null)
  const nothingSelected = props.selectedCount === 0

  return (
    <header className="toolbar">
      <div className="group icons" role="radiogroup" aria-label={T.tool}>
        {tools(T).map((t) => (
          <button
            key={t.tool}
            type="button"
            role="radio"
            aria-checked={props.tool === t.tool}
            aria-label={t.label}
            disabled={props.readOnly && t.tool !== 'pan'}
            className={`icon${props.tool === t.tool && !props.readOnly ? ' on' : ''}`}
            title={props.readOnly ? T.no_drawing_here : t.hint}
            onClick={() => props.onTool(t.tool)}
          >
            <t.icon />
          </button>
        ))}
      </div>

      <div className="group">
        {/* ⚠ *Clear the plan* is GONE, not disabled. In the lab it emptied
            `localStorage`; here the same gesture diffs to removing every
            room, every bookcase and every storey of the household's real map
            — and each case removal empties its slots first, which detaches
            the shelves the books actually stand on. One `confirm()` inherited
            from a throwaway app is not the door that belongs in front of
            that. If the owner ever wants it back it needs its own screen: the
            counts it would touch, and how many of those shelves hold books,
            BEFORE the call — the split P6.2 already reports. */}
        <Menu
          label={T.menu_plan}
          items={[
            { label: T.reload, onSelect: props.onReload },
            { label: T.trace, onSelect: () => underlayRef.current?.click() },
          ]}
        />
        <Menu
          label={T.menu_edit}
          items={[
            { label: T.undo, shortcut: 'Ctrl+Z', disabled: !props.canUndo, onSelect: props.onUndo },
            { label: T.redo, shortcut: 'Ctrl+Y', disabled: !props.canRedo, onSelect: props.onRedo },
            { label: T.copy, shortcut: 'Ctrl+C', disabled: nothingSelected, onSelect: props.onCopy },
            { label: T.paste, shortcut: 'Ctrl+V', disabled: !props.canPaste, onSelect: props.onPaste },
            {
              label: props.selectedCount > 1
                ? T.delete_many(props.selectedCount) : T.delete,
              shortcut: 'Del',
              disabled: nothingSelected,
              danger: true,
              onSelect: props.onDelete,
            },
          ]}
        />
        <Menu
          label={T.menu_view}
          items={[
            { label: T.zoom_in, shortcut: '+', onSelect: () => props.onZoom(1.25) },
            { label: T.zoom_out, shortcut: '−',
              onSelect: () => props.onZoom(1 / 1.25) },
            { label: T.show_all, onSelect: props.onFit },
            {
              label: T.ghost_floors,
              checked: props.ghosts,
              disabled: !props.manyFloors,
              onSelect: () => props.onGhosts(!props.ghosts),
            },
            {
              label: props.theme === 'dark' ? T.white_bg : T.black_bg,
              onSelect: () => props.onTheme(props.theme === 'dark' ? 'light' : 'dark'),
            },
          ]}
        />
        {/* ⚠ There is no *Apartment* menu any more. It offered *Draw room* and
            *Draw bookcase* — the two permanent radio buttons three inches to
            its left, under the same names — which is both a duplicate control
            and two things announcing one accessible name (CLAUDE.md). It also
            contradicted the rule that shrank this toolbar in the first place:
            a command lives in a menu, and only the TOOLS get a button. Its
            third item, the tracing underlay, is a thing you do to the plan and
            moved into the Plan menu, which stopped being a menu of one. */}
      </div>

      {props.underlay && (
        <div className="group">
          <label className="slider">
            <span>{T.trace_fade_short}</span>
            <input
              type="range"
              min={5}
              max={100}
              value={Math.round(props.underlay.opacity * 100)}
              aria-label={T.trace_opacity}
              onChange={(e) => props.onUnderlayChange({ opacity: Number(e.target.value) / 100 })}
            />
          </label>
          <label className="slider">
            <span>{T.trace_size_short}</span>
            <input
              type="range"
              min={10}
              max={200}
              value={Math.round(props.underlay.scale)}
              aria-label={T.trace_size}
              onChange={(e) => props.onUnderlayChange({ scale: Number(e.target.value) })}
            />
          </label>
          <button type="button" onClick={props.onUnderlayClear} aria-label={T.trace_remove}>
            ✕
          </button>
        </div>
      )}

      <div className="group right">
        {/* ⚠ The lab's tooltip named browser storage and a *File ▸ Save to
            file* menu; the port kept it after deleting the menu, so the one
            place that explains saving pointed at a control that no longer
            exists. Neither half was true here: the plan is in the library. */}
        <span
          className={`saved saved-${props.saved}`}
          role="status"
          title={T.saved_hint}
        >
          {savedText(T)[props.saved]}
        </span>
      </div>

      <input
        ref={underlayRef}
        type="file"
        accept="image/*"
        hidden
        aria-label={T.trace_upload}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) props.onUnderlay(f)
          e.target.value = ''
        }}
      />
    </header>
  )
}
