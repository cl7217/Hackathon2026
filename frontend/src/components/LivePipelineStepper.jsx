import { Check, Circle, LoaderCircle } from 'lucide-react'

const STAGES = [
  { id: 'ingestion', label: 'קליטת המסמך ורינדור עמודים' },
  { id: 'classification', label: 'סיווג וניתוח מבנה' },
  { id: 'extraction', label: 'OCR והשלמת אזורים לא ודאיים' },
  { id: 'validation', label: 'נרמול ואימות כללים' },
]

export default function LivePipelineStepper({ activeStage }) {
  const activeIndex = STAGES.findIndex((stage) => stage.id === activeStage)

  return (
    <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="התקדמות עיבוד הטפסים">
      {STAGES.map((stage, index) => {
        const complete = activeStage === 'complete' || index < activeIndex
        const active = stage.id === activeStage
        return (
          <li
            key={stage.id}
            aria-current={active ? 'step' : undefined}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
              complete
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : active
                  ? 'border-blue-200 bg-blue-50 font-semibold text-blue-800'
                  : 'border-slate-200 bg-white text-slate-400'
            }`}
          >
            {complete
              ? <Check size={16} aria-hidden="true" />
              : active
                ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
                : <Circle size={16} aria-hidden="true" />}
            <span>{stage.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
