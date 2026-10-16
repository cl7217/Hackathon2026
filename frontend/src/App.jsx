import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Eye,
  FileImage,
  FileSpreadsheet,
  FileText,
  HeartPulse,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from 'lucide-react'
import * as XLSX from '@e965/xlsx'

const ACCEPTED_TYPES = ['application/pdf', 'image/png', 'image/jpeg']
const ACCEPTED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']
const MAX_FILE_SIZE = 20 * 1024 * 1024
const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const EXTRACT_ENDPOINT = import.meta.env.VITE_EXTRACT_ENDPOINT || '/extract'
const CONFIDENCE_THRESHOLD = 0.75

const RESULT_FIELDS = [
  { key: 'firstName', label: 'שם פרטי', aliases: ['first_name', 'patient_first_name', 'patientFirstName', 'firstName'] },
  { key: 'lastName', label: 'שם משפחה', aliases: ['last_name', 'patient_last_name', 'patientLastName', 'lastName'] },
  { key: 'idNumber', label: 'תעודת זהות', aliases: ['id_number', 'patient_id', 'identity_number', 'idNumber'] },
  { key: 'healthFund', label: 'קופת חולים', aliases: ['health_fund', 'healthFund', 'hmo', 'insurer', 'payer', 'kupat_holim'] },
  { key: 'centerNumber', label: 'מספר מרכזי', aliases: ['center_number', 'medical_center_number', 'centerNumber'] },
  { key: 'documentDate', label: 'תאריך מסמך', aliases: ['document_date', 'date', 'documentDate'] },
  { key: 'sender', label: 'גורם שולח', aliases: ['sender', 'sending_entity', 'referring_entity'] },
  { key: 'commitmentNumber', label: 'מספר התחייבות', aliases: ['commitment_number', 'commitmentNumber'] },
  { key: 'receivedStamp', label: 'חותמת התקבל', aliases: ['received_stamp', 'receivedStamp', 'stamp_received', 'received', 'stamp'] },
]

function formatFileSize(bytes) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getFieldValue(source) {
  if (source === true) return 'כן'
  if (source === false) return 'לא'
  if (typeof source === 'string' || typeof source === 'number') return String(source)
  if (source && typeof source === 'object') {
    const value = source.value ?? source.text ?? source.extracted_value
    return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
  }
  return ''
}

function normalizeResults(payload) {
  const data = payload?.data ?? payload?.result ?? payload
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('התקבלה תשובה לא תקינה מהשרת. נסו שוב או פנו לתמיכה.')
  }

  const confidenceData = data.confidences ?? data.field_confidence ?? data.confidence
  const reviewFields = data.needs_review_fields ?? data.low_confidence_fields ?? payload?.needs_review_fields
  const reviewSet = new Set(Array.isArray(reviewFields) ? reviewFields.map(String) : [])

  const values = {}
  const uncertain = {}
  for (const field of RESULT_FIELDS) {
    const sourceKey = field.aliases.find((key) => data[key] !== undefined && data[key] !== null)
    const source = sourceKey ? data[sourceKey] : undefined
    const value = getFieldValue(source)
    const fieldObject = source && typeof source === 'object' ? source : {}
    const confidenceValue =
      fieldObject.confidence ??
      fieldObject.score ??
      (sourceKey && confidenceData && typeof confidenceData === 'object'
        ? confidenceData[sourceKey] ?? confidenceData[field.key]
        : undefined)
    const confidence = Number(confidenceValue)
    const flagged =
      fieldObject.needs_review === true ||
      fieldObject.uncertain === true ||
      fieldObject.low_confidence === true ||
      reviewSet.has(sourceKey) ||
      reviewSet.has(field.key) ||
      (Number.isFinite(confidence) && confidence < (confidence > 1 ? CONFIDENCE_THRESHOLD * 100 : CONFIDENCE_THRESHOLD))

    values[field.key] = value
    uncertain[field.key] = flagged || !value
  }

  return { values, uncertain }
}

function validateFile(file) {
  const extension = `.${file.name.split('.').pop()?.toLowerCase()}`
  if (!ACCEPTED_TYPES.includes(file.type) && !ACCEPTED_EXTENSIONS.includes(extension)) {
    return 'אפשר להעלות קובצי PDF, PNG או JPG בלבד.'
  }
  if (file.size > MAX_FILE_SIZE) {
    return 'גודל הקובץ חורג מ־20MB. בחרו קובץ קטן יותר.'
  }
  return ''
}

function App() {
  const inputRef = useRef(null)
  const [documents, setDocuments] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [previewId, setPreviewId] = useState(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [uploadError, setUploadError] = useState('')

  useEffect(() => {
    if (previewUrl) return () => URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  const previewDocument = documents.find((document) => document.id === previewId)
  const pendingCount = documents.filter((document) => document.status === 'pending' || document.status === 'error').length
  const approvedCount = documents.filter((document) => document.approved).length

  function addFiles(fileList) {
    const selectedFiles = Array.from(fileList || [])
    if (!selectedFiles.length) return

    const nextDocuments = []
    const errors = []
    selectedFiles.forEach((file) => {
      const validationError = validateFile(file)
      if (validationError) {
        errors.push(`${file.name}: ${validationError}`)
        return
      }
      nextDocuments.push({
        id: crypto.randomUUID(),
        file,
        values: {},
        uncertain: {},
        reviewed: {},
        approved: false,
        status: 'pending',
        error: '',
      })
    })

    if (nextDocuments.length) {
      setDocuments((current) => [...current, ...nextDocuments])
    }
    setUploadError(errors.join(' '))
    if (inputRef.current) inputRef.current.value = ''
  }

  function updateDocument(id, update) {
    setDocuments((current) =>
      current.map((document) =>
        document.id === id
          ? { ...document, ...update, approved: update.approved ?? false }
          : document,
      ),
    )
  }

  function removeDocument(id) {
    setDocuments((current) => current.filter((document) => document.id !== id))
    if (previewId === id) closePreview()
  }

  async function extractDocuments() {
    if (isProcessing) return
    const queue = documents.filter((document) => document.status === 'pending' || document.status === 'error')
    if (!queue.length) return

    setIsProcessing(true)
    setUploadError('')
    for (const document of queue) {
      setDocuments((current) =>
        current.map((item) => item.id === document.id ? { ...item, status: 'processing', error: '' } : item),
      )

      try {
        const body = new FormData()
        body.append('file', document.file)
        const response = await fetch(`${API_BASE_URL}${EXTRACT_ENDPOINT}`, { method: 'POST', body })

        if (!response.ok) {
          let detail = ''
          try {
            const errorBody = await response.json()
            detail = errorBody.detail || errorBody.message || ''
          } catch {
            // The service may return a non-JSON error response.
          }
          throw new Error(detail || `השרת החזיר שגיאה (${response.status}). נסו שוב.`)
        }

        const result = normalizeResults(await response.json())
        setDocuments((current) =>
          current.map((item) =>
            item.id === document.id
              ? { ...item, ...result, reviewed: {}, approved: false, status: 'complete', error: '' }
              : item,
          ),
        )
      } catch (requestError) {
        const message = requestError instanceof TypeError
          ? 'לא ניתן להתחבר לשירות החילוץ. בדקו את החיבור ונסו שוב.'
          : requestError.message || 'החילוץ נכשל. נסו שוב בעוד רגע.'
        setDocuments((current) =>
          current.map((item) =>
            item.id === document.id ? { ...item, status: 'error', error: message } : item,
          ),
        )
      }
    }
    setIsProcessing(false)
  }

  function openPreview(document) {
    setPreviewUrl(URL.createObjectURL(document.file))
    setPreviewId(document.id)
  }

  function closePreview() {
    setPreviewId(null)
    setPreviewUrl('')
  }

  function editField(document, field, value) {
    setDocuments((current) =>
      current.map((item) =>
        item.id === document.id
          ? {
              ...item,
              values: { ...item.values, [field.key]: value },
              reviewed: { ...item.reviewed, [field.key]: true },
              approved: false,
            }
          : item,
      ),
    )
  }

  function markFieldReviewed(document, field) {
    setDocuments((current) =>
      current.map((item) =>
        item.id === document.id
          ? { ...item, reviewed: { ...item.reviewed, [field.key]: true }, approved: false }
          : item,
      ),
    )
  }

  function approveDocument(document) {
    const hasUnreviewedFields = RESULT_FIELDS.some(
      (field) => document.uncertain[field.key] && !document.reviewed[field.key],
    )
    if (hasUnreviewedFields || document.status !== 'complete') return
    updateDocument(document.id, { approved: true })
  }

  async function exportApprovedDocuments() {
    const approved = documents.filter((document) => document.approved)
    if (!approved.length) return

    setIsExporting(true)
    setUploadError('')
    try {
      const XLSX = await import('@e965/xlsx')
      const rows = approved.map((document) => ({
        'שם הקובץ': document.file.name,
        ...Object.fromEntries(RESULT_FIELDS.map((field) => [field.label, document.values[field.key] || ''])),
      }))
      const worksheet = XLSX.utils.json_to_sheet(rows)
      worksheet['!cols'] = [{ wch: 32 }, ...RESULT_FIELDS.map(() => ({ wch: 20 }))]
      const workbook = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(workbook, worksheet, 'טפסים מאושרים')
      XLSX.writeFile(workbook, 'טפסים-מאושרים.xlsx')
    } catch (exportError) {
      setUploadError(`ייצוא לאקסל נכשל: ${exportError.message || 'נסו שוב.'}`)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#f6f9fc]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-gradient-to-b from-[#eaf5fc] via-[#f1f8fc] to-transparent" />

      <header className="relative border-b border-slate-200/80 bg-white/70">
        <div className="mx-auto flex h-[76px] max-w-7xl items-center justify-between px-5 sm:px-8">
          <a href="#" className="flex items-center gap-3" aria-label="MedExtract - דף הבית">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#e6f3fb] text-[#2776a8]">
              <HeartPulse size={22} strokeWidth={2.2} />
            </span>
            <span className="text-[17px] font-extrabold tracking-tight text-[#15324e]">
              Med<span className="text-[#3987b6]">Extract</span>
            </span>
          </a>
          <div className="hidden items-center gap-2 rounded-full border border-[#dce9f0] bg-white px-3.5 py-2 text-xs font-medium text-slate-500 sm:flex">
            <LockKeyhole size={14} className="text-[#4b8b71]" />
            המסמכים מעובדים באופן מאובטח
          </div>
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-slate-400 ring-1 ring-slate-200 sm:hidden">
            <ShieldCheck size={17} />
          </span>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl px-5 pb-16 pt-10 sm:px-8 sm:pt-14">
        <section className="mx-auto max-w-2xl text-center">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#dcebf4] bg-white/80 px-3.5 py-1.5 text-xs font-semibold text-[#4680a2] shadow-sm">
            <Sparkles size={14} />
            חילוץ ובדיקת מסמכים רפואיים
          </div>
          <h1 className="text-3xl font-extrabold leading-tight tracking-tight text-[#17344f] sm:text-[42px]">
            טפסים מסודרים,
            <span className="text-[#3987b6]"> בלי הקלדה מיותרת</span>
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-[15px] leading-7 text-slate-500 sm:text-base">
            העלו כמה טפסים יחד, בדקו שדות לא ודאיים, ערכו ואשרו לפני הייצוא לאקסל.
          </p>
        </section>

        <section className="mx-auto mt-9 max-w-4xl overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card sm:mt-11">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 sm:px-7">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#eef7fc] text-[#4389b4]">
                <FileText size={18} />
              </span>
              <div>
                <h2 className="text-sm font-bold text-slate-800">העלאת טפסים</h2>
                <p className="mt-0.5 text-xs text-slate-400">PDF, PNG או JPG · עד 20MB לקובץ</p>
              </div>
            </div>
            <span className="hidden items-center gap-1.5 text-xs text-slate-400 sm:flex">
              <ShieldCheck size={15} className="text-[#68a489]" />
              חיבור מאובטח
            </span>
          </div>

          <div className="p-5 sm:p-7">
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              className="sr-only"
              aria-label="בחירת טפסים רפואיים"
              onChange={(event) => addFiles(event.target.files)}
            />
            <button
              type="button"
              className={`group flex min-h-[176px] w-full flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 text-center transition-colors ${
                isDragging
                  ? 'border-[#4a9ac6] bg-[#eef8fd]'
                  : 'border-[#d7e4ec] bg-[#fbfdfe] hover:border-[#8dbbd4] hover:bg-[#f7fbfd]'
              }`}
              onClick={() => inputRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setIsDragging(false)
                addFiles(event.dataTransfer.files)
              }}
            >
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#eaf5fb] text-[#4d94bc] transition-transform group-hover:-translate-y-0.5">
                <Upload size={22} strokeWidth={1.8} />
              </span>
              <span className="text-[15px] font-bold text-slate-700">גררו לכאן כמה טפסים</span>
              <span className="mt-1.5 text-sm text-slate-400">או לחצו לבחירת קבצים מהמכשיר</span>
            </button>

            {uploadError && (
              <div role="alert" className="mt-4 flex items-start gap-2.5 rounded-lg border border-rose-100 bg-rose-50 px-3.5 py-3 text-sm text-rose-700">
                <AlertCircle size={17} className="mt-0.5 shrink-0" />
                <span>{uploadError}</span>
              </div>
            )}

            <div className="mt-5 flex flex-col-reverse items-center justify-between gap-4 sm:flex-row">
              <p className="flex items-center gap-1.5 text-xs leading-5 text-slate-400">
                <LockKeyhole size={14} className="shrink-0 text-slate-400" />
                הקבצים משמשים לחילוץ בלבד ואינם נשמרים במערכת.
              </p>
              <button
                type="button"
                disabled={!pendingCount || isProcessing}
                onClick={extractDocuments}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#287eae] px-6 py-3 text-sm font-bold text-white shadow-sm shadow-[#287eae]/20 transition hover:bg-[#206d99] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none sm:w-auto"
              >
                {isProcessing ? (
                  <>
                    <LoaderCircle size={17} className="animate-spin" />
                    מעבד טפסים...
                  </>
                ) : (
                  <>
                    {pendingCount
                      ? `חלץ ${pendingCount} טפסים`
                      : documents.length ? 'החילוץ הושלם' : 'חלץ טפסים'}
                    <ArrowLeft size={17} />
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        {documents.length > 0 && (
          <section className="mx-auto mt-6 max-w-7xl overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-7">
              <div>
                <h2 className="text-base font-bold text-slate-800">תוצאות חילוץ</h2>
                <p className="mt-1 text-xs text-slate-400">
                  {documents.length} טפסים · {approvedCount} אושרו
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
                  <AlertCircle size={14} />
                  כתום = נדרשת בדיקה
                </span>
                <button
                  type="button"
                  disabled={!approvedCount || isExporting}
                  onClick={exportApprovedDocuments}
                  className="flex items-center gap-2 rounded-lg bg-[#287eae] px-4 py-2.5 text-sm font-bold text-white transition hover:bg-[#206d99] disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {isExporting ? <LoaderCircle size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}
                  {isExporting ? 'מייצא...' : `ייצוא ${approvedCount ? `${approvedCount} לאקסל` : 'לאקסל'}`}
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[1450px] border-collapse text-right text-sm">
                <thead className="bg-slate-50 text-xs font-semibold text-slate-500">
                  <tr>
                    <th className="sticky right-0 z-10 bg-slate-50 px-4 py-3"># / קובץ</th>
                    {RESULT_FIELDS.map((field) => <th key={field.key} className="px-4 py-3">{field.label}</th>)}
                    <th className="px-4 py-3">מצב</th>
                    <th className="px-4 py-3">פעולות</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {documents.map((document, index) => {
                    const unreviewedCount = RESULT_FIELDS.filter(
                      (field) => document.uncertain[field.key] && !document.reviewed[field.key],
                    ).length
                    const canApprove = document.status === 'complete' && !unreviewedCount
                    return (
                      <tr key={document.id} className="align-top hover:bg-slate-50/60">
                        <td className="sticky right-0 z-[1] max-w-[220px] bg-white px-4 py-4 hover:bg-slate-50">
                          <div className="flex items-start gap-2">
                            {document.file.type === 'application/pdf'
                              ? <FileText size={16} className="mt-0.5 shrink-0 text-[#4d94bc]" />
                              : <FileImage size={16} className="mt-0.5 shrink-0 text-[#4d94bc]" />}
                            <div className="min-w-0">
                              <span className="block text-xs text-slate-400">טופס {index + 1}</span>
                              <span className="mt-1 block truncate font-semibold text-slate-700" title={document.file.name}>{document.file.name}</span>
                            </div>
                          </div>
                        </td>
                        {RESULT_FIELDS.map((field) => {
                          const needsReview = document.uncertain[field.key] && !document.reviewed[field.key]
                          return (
                            <td key={field.key} className="px-4 py-4">
                              <span className={`inline-block max-w-[180px] truncate rounded-md px-2 py-1 ${
                                needsReview
                                  ? 'bg-amber-100 font-semibold text-amber-800 ring-1 ring-amber-200'
                                  : document.values[field.key]
                                    ? 'text-slate-700'
                                    : 'text-slate-400'
                              }`} title={document.values[field.key] || (needsReview ? 'לא זוהה — נדרשת בדיקה' : '')}>
                                {document.values[field.key] || (needsReview ? 'לא בטוח — בדקי' : 'לא זוהה')}
                              </span>
                            </td>
                          )
                        })}
                        <td className="whitespace-nowrap px-4 py-4">
                          {document.status === 'processing' && <span className="flex items-center gap-1.5 text-xs text-blue-600"><LoaderCircle size={14} className="animate-spin" /> בעיבוד</span>}
                          {document.status === 'pending' && <span className="text-xs text-slate-400">ממתין לחילוץ</span>}
                          {document.status === 'error' && <span className="text-xs text-rose-600" title={document.error}>החילוץ נכשל</span>}
                          {document.status === 'complete' && document.approved && <span className="flex items-center gap-1 text-xs font-semibold text-emerald-700"><CheckCircle2 size={14} /> אושר</span>}
                          {document.status === 'complete' && !document.approved && (
                            <span className={`text-xs ${unreviewedCount ? 'text-amber-700' : 'text-slate-500'}`}>
                              {unreviewedCount ? `${unreviewedCount} שדות לבדיקה` : 'מוכן לאישור'}
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            {document.status === 'complete' && (
                              <button
                                type="button"
                                onClick={() => openPreview(document)}
                                className="flex items-center gap-1 rounded-md px-2.5 py-2 text-xs font-semibold text-[#397b9e] hover:bg-[#eff7fb]"
                              >
                                <Eye size={14} /> צפייה ועריכה
                              </button>
                            )}
                            {document.status === 'complete' && (
                              <button
                                type="button"
                                disabled={!canApprove && !document.approved}
                                onClick={() => approveDocument(document)}
                                className="flex items-center gap-1 rounded-md px-2.5 py-2 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:text-slate-300"
                                title={unreviewedCount ? 'יש לבדוק את השדות המסומנים לפני האישור' : ''}
                              >
                                <Check size={14} /> {document.approved ? 'אושר' : 'אישור'}
                              </button>
                            )}
                            {document.status === 'error' && (
                              <button type="button" onClick={extractDocuments} className="rounded-md px-2.5 py-2 text-xs font-semibold text-[#397b9e] hover:bg-[#eff7fb]">
                                <RotateCcw size={14} />
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => removeDocument(document.id)}
                              aria-label={`הסרת ${document.file.name}`}
                              className="rounded-md p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                            >
                              <X size={15} />
                            </button>
                          </div>
                          {document.error && <p className="mt-1 max-w-[250px] text-xs text-rose-600">{document.error}</p>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <footer className="mx-auto mt-8 flex max-w-4xl items-center justify-center gap-2 text-xs text-slate-400">
          <ShieldCheck size={15} className="text-[#70a28b]" />
          המידע מוצג למטרת עיבוד המסמך בלבד
        </footer>
      </main>

      {previewDocument && previewUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-3 sm:p-6"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closePreview()
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="review-title"
            className="flex max-h-[95vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
            dir="rtl"
          >
            <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
              <div className="min-w-0">
                <h2 id="review-title" className="text-base font-bold text-slate-800">בדיקה ועריכה ידנית</h2>
                <p className="mt-1 truncate text-xs text-slate-400">{previewDocument.file.name}</p>
              </div>
              <button type="button" onClick={closePreview} aria-label="סגירה" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100">
                <X size={20} />
              </button>
            </header>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-2 lg:overflow-hidden">
              <div className="flex min-h-[320px] items-center justify-center bg-slate-100 p-3 lg:min-h-0">
                {previewDocument.file.type === 'application/pdf' ? (
                  <iframe title={`תצוגת ${previewDocument.file.name}`} src={previewUrl} className="h-[55vh] w-full rounded-lg bg-white lg:h-full" />
                ) : (
                  <img src={previewUrl} alt={`תצוגת ${previewDocument.file.name}`} className="max-h-[55vh] max-w-full rounded-lg object-contain lg:max-h-full" />
                )}
              </div>

              <div className="min-h-0 overflow-y-auto p-5 sm:p-7">
                <p className="mb-4 text-sm leading-6 text-slate-500">
                  עברו על הערכים שסומנו בכתום. אפשר לערוך כל שדה; שדה לא ודאי חייב להיבדק לפני האישור.
                </p>
                <div className="space-y-4">
                  {RESULT_FIELDS.map((field) => {
                    const needsReview = previewDocument.uncertain[field.key] && !previewDocument.reviewed[field.key]
                    const isReviewed = previewDocument.uncertain[field.key] && previewDocument.reviewed[field.key]
                    return (
                      <div key={field.key} className={`rounded-xl border p-3.5 ${needsReview ? 'border-amber-200 bg-amber-50/70' : 'border-slate-200 bg-white'}`}>
                        <label htmlFor={`field-${field.key}`} className="mb-1.5 block text-xs font-semibold text-slate-600">
                          {field.label} {needsReview && <span className="text-amber-700">· לא בטוח — בדקי</span>}
                          {isReviewed && <span className="text-emerald-700">· נבדק</span>}
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            id={`field-${field.key}`}
                            type="text"
                            value={previewDocument.values[field.key] || ''}
                            onChange={(event) => editField(previewDocument, field, event.target.value)}
                            placeholder="לא זוהה — ניתן להזין ידנית"
                            className={`min-w-0 flex-1 rounded-lg border px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:ring-2 ${
                              needsReview
                                ? 'border-amber-300 bg-white focus:border-amber-400 focus:ring-amber-100'
                                : 'border-slate-200 focus:border-[#6ba4c2] focus:ring-[#e8f4fa]'
                            }`}
                          />
                          {needsReview && (
                            <button
                              type="button"
                              onClick={() => markFieldReviewed(previewDocument, field)}
                              className="shrink-0 rounded-lg border border-amber-300 bg-white px-2.5 py-2.5 text-xs font-semibold text-amber-800 hover:bg-amber-100"
                            >
                              בדקתי
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div className="sticky bottom-0 mt-5 flex items-center justify-between gap-3 border-t border-slate-100 bg-white py-4">
                  <span className="text-xs text-slate-400">
                    {RESULT_FIELDS.filter((field) => previewDocument.uncertain[field.key] && !previewDocument.reviewed[field.key]).length
                      ? 'נותרו שדות לבדיקה'
                      : 'כל השדות הלא ודאיים נבדקו'}
                  </span>
                  <button
                    type="button"
                    disabled={RESULT_FIELDS.some((field) => previewDocument.uncertain[field.key] && !previewDocument.reviewed[field.key])}
                    onClick={() => {
                      approveDocument(previewDocument)
                      closePreview()
                    }}
                    className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    <Check size={16} />
                    {previewDocument.approved ? 'אושר' : 'אישור הטופס'}
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

export default App
