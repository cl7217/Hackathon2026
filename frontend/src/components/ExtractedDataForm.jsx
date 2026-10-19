import { Check } from 'lucide-react'

function getBadge(state) {
  if (state === 'green') return ['מאומת', 'bg-emerald-100 text-emerald-800']
  if (state === 'orange') return ['נדרשת בדיקה', 'bg-amber-100 text-amber-800']
  return ['ריק', 'bg-slate-100 text-slate-500']
}

export default function ExtractedDataForm({
  fields,
  values,
  metadata,
  selectedField,
  reviewed,
  onSelectField,
  onChange,
  onBlur,
  onMarkReviewed,
}) {
  return (
    <div className="min-h-0 overflow-y-auto p-5 sm:p-7">
      <p className="mb-4 text-sm leading-6 text-slate-500">
        בחרו שדה כדי לראות את מיקומו במסמך. ערכים חסרים או לא ודאיים מסומנים לבדיקה.
      </p>
      <div className="space-y-3">
        {fields.map((field) => {
          const value = values[field.key] || ''
          const meta = metadata[field.key] || {}
          const needsReview = Boolean(meta.needsReview) && !reviewed[field.key]
          const [badge, badgeClass] = getBadge(
            !value ? 'empty' : needsReview ? 'orange' : meta.state || 'green',
          )
          return (
            <div
              key={field.key}
              className={`rounded-xl border p-3.5 ${
                selectedField === field.key
                  ? 'border-blue-300 ring-2 ring-blue-100'
                  : needsReview
                    ? 'border-amber-200 bg-amber-50/70'
                    : 'border-slate-200 bg-white'
              }`}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => onSelectField(field.key)}
                  className="text-right text-xs font-semibold text-slate-700 hover:text-blue-700"
                >
                  {field.label}
                  {meta.handwritten && <span className="mr-1 font-normal text-slate-400">· כתב יד</span>}
                </button>
                <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${badgeClass}`}>{badge}</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  id={`field-${field.key}`}
                  type="text"
                  value={value}
                  onFocus={() => onSelectField(field.key)}
                  onChange={(event) => onChange(field, event.target.value)}
                  onBlur={() => onBlur(field)}
                  aria-label={field.label}
                  className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  placeholder="לא זוהה — ניתן להזין ידנית"
                />
                {needsReview && (
                  <button
                    type="button"
                    onClick={() => onMarkReviewed(field)}
                    className="flex shrink-0 items-center gap-1 rounded-lg border border-amber-300 bg-white px-2.5 py-2.5 text-xs font-semibold text-amber-800 hover:bg-amber-100"
                  >
                    <Check size={14} /> בדקתי
                  </button>
                )}
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                <span>{meta.confidence != null ? `ביטחון ${Math.round(meta.confidence * 100)}%` : ''}</span>
                {meta.signals?.commitment_prefix_match === false && (
                  <span className="text-amber-700">קידומת התחייבות אינה תואמת לקופה</span>
                )}
                {meta.signals?.field_valid === false && field.key === 'idNumber' && (
                  <span className="text-amber-700">ספרת הביקורת של תעודת הזהות אינה תקינה</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
