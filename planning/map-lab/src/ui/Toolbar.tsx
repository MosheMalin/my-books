/**
 * The toolbar — and the mode switch that is the whole point of the lab.
 *
 * The two authoring models sit side by side rather than one being a setting
 * buried somewhere, because the owner is meant to draw the same house twice
 * and say which one to build (MAP_PLAN §4).
 */

import { useRef } from 'react'

import type { Underlay } from '../core/model'
import type { Mode, Tool } from './types'

type Props = {
  mode: Mode
  tool: Tool
  underlay: Underlay | null
  canUndo: boolean
  canRedo: boolean
  onMode: (m: Mode) => void
  onTool: (t: Tool) => void
  onUndo: () => void
  onRedo: () => void
  onFit: () => void
  onExport: () => void
  onImport: (file: File) => void
  onUnderlay: (file: File) => void
  onUnderlayChange: (patch: Partial<Underlay>) => void
  onUnderlayClear: () => void
  onClear: () => void
}

const TOOLS: Record<Mode, { tool: Tool; label: string; key: string }[]> = {
  D: [
    { tool: 'select', label: 'Select', key: '1' },
    { tool: 'room', label: 'Room', key: '2' },
    { tool: 'case', label: 'Bookcase', key: '3' },
    { tool: 'pan', label: 'Pan', key: '4' },
  ],
  S: [
    { tool: 'select', label: 'Select', key: '1' },
    { tool: 'draw', label: 'Draw', key: '2' },
    { tool: 'pan', label: 'Pan', key: '4' },
  ],
}

export function Toolbar(props: Props) {
  const importRef = useRef<HTMLInputElement | null>(null)
  const underlayRef = useRef<HTMLInputElement | null>(null)

  return (
    <header className="toolbar">
      <div className="brand">
        <strong>map lab</strong>
        <span className="tag">P6.0</span>
      </div>

      <div className="group" role="radiogroup" aria-label="authoring mode">
        <button
          type="button"
          role="radio"
          aria-checked={props.mode === 'D'}
          className={props.mode === 'D' ? 'on' : ''}
          onClick={() => props.onMode('D')}
          title="Walls and bookcases snap while you drag. Nothing is guessed."
        >
          D · snap
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={props.mode === 'S'}
          className={props.mode === 'S' ? 'on' : ''}
          onClick={() => props.onMode('S')}
          title="Draw freehand; the stroke is straightened when you lift. VISION §7 approach A."
        >
          S · straighten
        </button>
      </div>

      <div className="group" role="radiogroup" aria-label="tool">
        {TOOLS[props.mode].map((t) => (
          <button
            key={t.tool}
            type="button"
            role="radio"
            aria-checked={props.tool === t.tool}
            className={props.tool === t.tool ? 'on' : ''}
            onClick={() => props.onTool(t.tool)}
          >
            {t.label} <kbd>{t.key}</kbd>
          </button>
        ))}
      </div>

      <div className="group">
        <button type="button" onClick={props.onUndo} disabled={!props.canUndo} aria-label="undo">
          ↶
        </button>
        <button type="button" onClick={props.onRedo} disabled={!props.canRedo} aria-label="redo">
          ↷
        </button>
        <button type="button" onClick={props.onFit}>
          Fit
        </button>
      </div>

      <div className="group">
        <button type="button" onClick={() => underlayRef.current?.click()}>
          Trace a sketch…
        </button>
        <input
          ref={underlayRef}
          type="file"
          accept="image/*"
          hidden
          aria-label="upload a floor plan to trace"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) props.onUnderlay(f)
            e.target.value = ''
          }}
        />
        {props.underlay && (
          <>
            <label className="slider">
              <span>opacity</span>
              <input
                type="range"
                min={5}
                max={100}
                value={Math.round(props.underlay.opacity * 100)}
                aria-label="underlay opacity"
                onChange={(e) => props.onUnderlayChange({ opacity: Number(e.target.value) / 100 })}
              />
            </label>
            <label className="slider">
              <span>size</span>
              <input
                type="range"
                min={5}
                max={120}
                value={Math.round(props.underlay.scale)}
                aria-label="underlay size"
                onChange={(e) => props.onUnderlayChange({ scale: Number(e.target.value) })}
              />
            </label>
            <button type="button" onClick={props.onUnderlayClear} aria-label="remove the underlay">
              ✕
            </button>
          </>
        )}
      </div>

      <div className="group right">
        <button type="button" onClick={props.onExport}>
          Export
        </button>
        <button type="button" onClick={() => importRef.current?.click()}>
          Import
        </button>
        <input
          ref={importRef}
          type="file"
          accept="application/json,.json"
          hidden
          aria-label="import a plan file"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) props.onImport(f)
            e.target.value = ''
          }}
        />
        <button type="button" className="danger" onClick={props.onClear}>
          Clear
        </button>
      </div>
    </header>
  )
}
