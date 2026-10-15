import { useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  FileImage,
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

const ACCEPTED_TYPES = ['application/pdf', 'image/png', 'image/jpeg']
const MAX_FILE_SIZE = 20 * 1024 * 1024
const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const EXTRACT_ENDPOINT = import.meta.env.VITE_EXTRACT_ENDPOINT || '/extract'

const RESULT_FIELDS = [
  { key: 'firstName', label: 'שם פרטי', english: 'First name' },
  { key: 'lastName', label: 'שם משפחה', english: 'Last name' },
  { key: 'idNumber', label: 'תעודת זהות', english: 'ID number' },
  { key: 'centerNumber', label: 'מספר מרכזי', english: 'Center number' },
  { key: 'documentDate', label: 'תאריך מסמך', english: 'Document date' },
  { key: 'sender', label: 'גורם שולח', english: 'Sender' },
  { key: 'commitmentNumber', label: 'מספר התחייבות', english: 'Commitment number' },
]

const FIELD_ALIASES = {
  firstName: ['first_name', 'patient_first_name', 'patientFirstName', 'firstName'],
  lastName: ['last_name', 'patient_last_name', 'patientLastName', 'lastName'],
  idNumber: ['id_number', 'patient_id', 'identity_number', 'idNumber'],
  centerNumber: ['center_number', 'medical_center_number', 'centerNumber'],
  documentDate: ['document_date', 'date', 'documentDate'],
  sender: ['sender', 'sending_entity', 'referring_entity'],
  commitmentNumber: ['commitment_number', 'commitmentNumber'],
}

function normalizeResults(payload) {
  const data = payload?.data ?? payload?.result ?? payload
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('התקבלה תשובה לא תקינה מהשרת. נסו שוב או פנו לתמיכה.')
  }

  return Object.fromEntries(
    Object.entries(FIELD_ALIASES).map(([field, aliases]) => {
      const match = aliases.find((key) => data[key] !== undefined && data[key] !== null)
      const value = match ? data[match] : ''
      return [field, typeof value === 'string' || typeof value === 'number' ? String(value) : '']
    }),
  )
}

function formatFileSize(bytes) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function App() {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState(null)

  function validateFile(selectedFile) {
    if (!ACCEPTED_TYPES.includes(selectedFile.type)) {
      return 'אפשר להעלות קובצי PDF, PNG או JPG בלבד.'
    }
    if (selectedFile.size > MAX_FILE_SIZE) {
      return 'גודל הקובץ חורג מ־20MB. בחרו קובץ קטן יותר.'
    }
    return ''
  }

  function selectFile(selectedFile) {
    if (!selectedFile) return
    const validationError = validateFile(selectedFile)
    setResults(null)
    setError(validationError)
    setFile(validationError ? null : selectedFile)
    if (inputRef.current) inputRef.current.value = ''
  }

  function removeFile() {
    setFile(null)
    setResults(null)
    setError('')
    if (inputRef.current) inputRef.current.value = ''
  }

  async function handleExtract() {
    if (!file || isLoading) return

    setIsLoading(true)
    setError('')
    setResults(null)

    try {
      const body = new FormData()
      body.append('file', file)

      const response = await fetch(`${API_BASE_URL}${EXTRACT_ENDPOINT}`, {
        method: 'POST',
        body,
      })

      if (!response.ok) {
        let detail = ''
        try {
          const errorBody = await response.json()
          detail = errorBody.detail || errorBody.message || ''
        } catch {
          // The server may return a non-JSON error response.
        }
        throw new Error(detail || `השרת החזיר שגיאה (${response.status}). נסו שוב.`)
      }

      const payload = await response.json()
      setResults(normalizeResults(payload))
    } catch (requestError) {
      setError(
        requestError instanceof TypeError
          ? 'לא ניתן להתחבר לשרת. בדקו שהשירות פועל בכתובת שהוגדרה ונסו שוב.'
          : requestError.message || 'החילוץ נכשל. נסו שוב בעוד רגע.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  function handleDrop(event) {
    event.preventDefault()
    setIsDragging(false)
    selectFile(event.dataTransfer.files?.[0])
  }

  const isPdf = file?.type === 'application/pdf'

  return (
    <div className="min-h-screen overflow-hidden bg-[#f6f9fc]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-gradient-to-b from-[#eaf5fc] via-[#f1f8fc] to-transparent" />

      <header className="relative border-b border-slate-200/80 bg-white/70">
        <div className="mx-auto flex h-[76px] max-w-6xl items-center justify-between px-5 sm:px-8">
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
            מסמכיכם מעובדים באופן מאובטח
          </div>
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-slate-400 ring-1 ring-slate-200 sm:hidden">
            <ShieldCheck size={17} />
          </span>
        </div>
      </header>

      <main className="relative mx-auto max-w-6xl px-5 pb-16 pt-10 sm:px-8 sm:pt-14">
        <section className="mx-auto max-w-2xl text-center">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#dcebf4] bg-white/80 px-3.5 py-1.5 text-xs font-semibold text-[#4680a2] shadow-sm">
            <Sparkles size={14} />
            חילוץ חכם של מסמכים רפואיים
          </div>
          <h1 className="text-3xl font-extrabold leading-tight tracking-tight text-[#17344f] sm:text-[42px]">
            פחות הקלדה,
            <span className="text-[#3987b6]"> יותר זמן לטיפול</span>
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-[15px] leading-7 text-slate-500 sm:text-base">
            מעלים טופס התחייבות רפואית ומקבלים את הפרטים החשובים מסודרים,
            מדויקים ומוכנים לעבודה.
          </p>
        </section>

        <section className="mx-auto mt-9 max-w-[760px] overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card sm:mt-11">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 sm:px-7">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#eef7fc] text-[#4389b4]">
                <FileText size={18} />
              </span>
              <div>
                <h2 className="text-sm font-bold text-slate-800">העלאת מסמך</h2>
                <p className="mt-0.5 text-xs text-slate-400">העלו טופס התחייבות לחילוץ</p>
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
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              className="sr-only"
              aria-label="בחירת מסמך רפואי"
              onChange={(event) => selectFile(event.target.files?.[0])}
            />

            {!file ? (
              <button
                type="button"
                className={`group flex min-h-[230px] w-full flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 text-center transition-colors ${
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
                onDrop={handleDrop}
              >
                <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#eaf5fb] text-[#4d94bc] transition-transform group-hover:-translate-y-0.5">
                  <Upload size={24} strokeWidth={1.8} />
                </span>
                <span className="text-[15px] font-bold text-slate-700">
                  גררו לכאן את המסמך
                </span>
                <span className="mt-1.5 text-sm text-slate-400">או לחצו לבחירת קובץ מהמכשיר</span>
                <span className="mt-4 rounded-md bg-white px-2.5 py-1 text-[11px] font-medium text-slate-400 ring-1 ring-slate-200">
                  PDF, PNG, JPG <span dir="ltr">· עד 20MB</span>
                </span>
              </button>
            ) : (
              <div className="flex min-h-[150px] items-center justify-between gap-4 rounded-xl border border-[#dce9f0] bg-[#fbfdfe] p-4 sm:px-6">
                <div className="flex min-w-0 items-center gap-4">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#eaf5fb] text-[#4d94bc]">
                    {isPdf ? <FileText size={22} /> : <FileImage size={22} />}
                  </span>
                  <div className="min-w-0 text-right">
                    <p className="truncate text-sm font-bold text-slate-700">{file.name}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      {isPdf ? 'מסמך PDF' : 'תמונה'} · {formatFileSize(file.size)}
                    </p>
                    <p className="mt-2 flex items-center gap-1 text-[11px] font-medium text-[#579276]">
                      <CheckCircle2 size={13} />
                      מוכן לחילוץ
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={removeFile}
                  aria-label="הסרת הקובץ"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-rose-50 hover:text-rose-500"
                >
                  <X size={18} />
                </button>
              </div>
            )}

            {error && (
              <div
                role="alert"
                className="mt-4 flex items-start gap-2.5 rounded-lg border border-rose-100 bg-rose-50 px-3.5 py-3 text-sm text-rose-700"
              >
                <AlertCircle size={17} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <div className="mt-5 flex flex-col-reverse items-center justify-between gap-4 sm:flex-row">
              <p className="flex items-center gap-1.5 text-xs leading-5 text-slate-400">
                <LockKeyhole size={14} className="shrink-0 text-slate-400" />
                הקובץ משמש לחילוץ בלבד ואינו נשמר במערכת.
              </p>
              <button
                type="button"
                disabled={!file || isLoading}
                onClick={handleExtract}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#287eae] px-6 py-3 text-sm font-bold text-white shadow-sm shadow-[#287eae]/20 transition hover:bg-[#206d99] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none sm:w-auto"
              >
                {isLoading ? (
                  <>
                    <LoaderCircle size={17} className="animate-spin" />
                    מעבד את המסמך...
                  </>
                ) : (
                  <>
                    חלץ נתונים
                    <ArrowLeft size={17} />
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        {results && (
          <section
            aria-live="polite"
            className="mx-auto mt-6 max-w-[760px] overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card"
          >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-7">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                  <CheckCircle2 size={19} />
                </span>
                <div>
                  <h2 className="text-sm font-bold text-slate-800">החילוץ הושלם בהצלחה</h2>
                  <p className="mt-0.5 text-xs text-slate-400">הנתונים שזוהו במסמך</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setResults(null)
                  setFile(null)
                }}
                className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-semibold text-[#4182a7] transition hover:bg-[#eff7fb]"
              >
                <RotateCcw size={14} />
                מסמך חדש
              </button>
            </div>
            <dl className="grid grid-cols-1 gap-px bg-slate-100 sm:grid-cols-2">
              {RESULT_FIELDS.map((field) => (
                <div key={field.key} className="min-h-[87px] bg-white px-5 py-4 sm:px-7">
                  <dt className="text-xs font-medium text-slate-400">{field.label}</dt>
                  <dd className="mt-2 flex items-center gap-2 text-[15px] font-semibold text-slate-700">
                    {results[field.key] ? (
                      <>
                        <Check size={15} className="shrink-0 text-[#5a9a79]" />
                        <span>{results[field.key]}</span>
                      </>
                    ) : (
                      <span className="font-normal text-slate-300">לא זוהה</span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        <footer className="mx-auto mt-8 flex max-w-[760px] items-center justify-center gap-2 text-xs text-slate-400">
          <ShieldCheck size={15} className="text-[#70a28b]" />
          המידע מוצג למטרת עיבוד המסמך בלבד
        </footer>
      </main>
    </div>
  )
}

export default App
