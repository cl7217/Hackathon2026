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
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from 'lucide-react'
import DocumentViewer from './components/DocumentViewer'
import ExtractedDataForm from './components/ExtractedDataForm'
import LivePipelineStepper from './components/LivePipelineStepper'

const ACCEPTED_TYPES = ['application/pdf', 'image/png', 'image/jpeg']
const ACCEPTED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']
const MAX_FILE_SIZE = 20 * 1024 * 1024
const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
const EXTRACT_ENDPOINT = import.meta.env.VITE_EXTRACT_ENDPOINT || '/extract'
const CONFIDENCE_THRESHOLD = 0.75
const HEALTH_FUND_PREFIXES = { clalit: '30', leumit: '12', meuhedet: '73', maccabi: '26' }
const HEALTH_FUND_NAMES = ['כללית', 'מכבי', 'מאוחדת', 'לאומית']
const SENDER_NAMES = [
  ...HEALTH_FUND_NAMES,
  'בית חולים', 'הדסה', 'שיבא', 'איכילוב', 'רמב״ם', 'רמבם', 'סורוקה',
  'בילינסון', 'שערי צדק', 'וולפסון', 'קפלן', 'אסף הרופא', 'ברזילי',
  'הלל יפה', 'זיו', 'פוריה', 'לניאדו', 'מעייני הישועה',
]

const RESULT_FIELDS = [
  { key: 'firstName', label: 'שם פרטי', aliases: ['first_name', 'patient_first_name', 'patientFirstName', 'firstName'] },
  { key: 'lastName', label: 'שם משפחה', aliases: ['last_name', 'patient_last_name', 'patientLastName', 'lastName'] },
  { key: 'idNumber', label: 'תעודת זהות', aliases: ['id_number', 'patient_id', 'identity_number', 'idNumber'] },
  { key: 'healthFund', label: 'קופת חולים', aliases: ['health_fund', 'healthFund', 'hmo', 'insurer', 'payer', 'kupat_holim'] },
  { key: 'centerNumber', label: 'מספר מרכזי', aliases: ['center_number', 'medical_center_number', 'centerNumber'] },
  { key: 'documentDate', label: 'תאריך קבלת הדגימה', aliases: ['document_date', 'date', 'documentDate'] },
  { key: 'sender', label: 'גורם שולח', aliases: ['sender', 'sending_entity', 'referring_entity'] },
  { key: 'commitmentNumber', label: 'מספר התחייבות', aliases: ['commitment_number', 'commitmentNumber'] },
  { key: 'receivedStamp', label: 'חותמת התקבל', aliases: ['received_stamp', 'receivedStamp', 'stamp_received', 'received', 'stamp'] },
]

function formatFileSize(bytes) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = url
  link.download = filename
  window.document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function downloadSpreadsheet(rows, filename) {
  const XLSX = await import('@e965/xlsx')
  const worksheet = XLSX.utils.json_to_sheet(rows)
  worksheet['!cols'] = Object.keys(rows[0] || {}).map((key) => ({
    wch: Math.min(Math.max(key.length + 4, 16), 36),
  }))
  worksheet['!views'] = [{ rightToLeft: true }]
  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, 'טפסים מאושרים')
  const content = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' })
  downloadBlob(
    new Blob([content], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
    filename,
  )
}

function getFieldValue(source) {
  if (source === true) return 'כן'
  if (source === false) return 'לא'
  if (Array.isArray(source)) return source.map(String).join(', ')
  if (typeof source === 'string' || typeof source === 'number') return String(source)
  if (source && typeof source === 'object') {
    const value = source.value ?? source.text ?? source.extracted_value
    if (Array.isArray(value)) return value.map(String).join(', ')
    return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
  }
  return ''
}

function validateEditedField(field, value, formType, healthFund) {
  if (!value.trim()) return { state: 'empty', needsReview: true }
  const compact = (input) => input.toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
  const values = value.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean)
  if (field.key === 'idNumber') {
    const id = value.replace(/\D/g, '').padStart(9, '0')
    const valid = /^\d{9}$/.test(id) && [...id].reduce((sum, digit, index) => {
      const product = Number(digit) * (index % 2 ? 2 : 1)
      return sum + Math.floor(product / 10) + product % 10
    }, 0) % 10 === 0
    return {
      state: valid ? 'green' : 'orange',
      needsReview: !valid,
      signals: { field_valid: valid },
    }
  }
  if (field.key === 'centerNumber') {
    const valid = values.length > 0 && values.every((item) => /^\d+(?:[\s./-]\d+)*$/.test(item))
    return {
      state: valid ? 'green' : 'orange',
      needsReview: !valid,
      signals: { numeric_format: valid },
    }
  }
  if (field.key === 'documentDate') {
    const match = value.trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
    const parsed = match
      ? new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]))
      : null
    const valid = Boolean(
      match &&
      parsed.getFullYear() === Number(match[3]) &&
      parsed.getMonth() === Number(match[2]) - 1 &&
      parsed.getDate() === Number(match[1]) &&
      parsed.getFullYear() >= 1900 &&
      parsed <= new Date(),
    )
    return {
      state: valid ? 'green' : 'orange',
      needsReview: !valid,
      signals: { field_valid: valid },
    }
  }
  if (field.key === 'sender' || field.key === 'healthFund') {
    const candidate = compact(value)
    const allowed = (field.key === 'healthFund' ? HEALTH_FUND_NAMES : SENDER_NAMES)
      .some((name) => candidate.includes(compact(name)))
    return {
      state: allowed ? 'green' : 'orange',
      needsReview: !allowed,
      signals: { field_valid: allowed },
    }
  }
  if (field.key === 'receivedStamp') {
    const valid = compact(value).includes(compact('התקבל'))
    return {
      state: valid ? 'green' : 'orange',
      needsReview: !valid,
      signals: { field_valid: valid },
    }
  }
  if (field.key === 'commitmentNumber') {
    const fundToIssuer = { כללית: 'clalit', מכבי: 'maccabi', מאוחדת: 'meuhedet', לאומית: 'leumit' }
    const matchedFund = Object.entries(fundToIssuer).find(([name]) => String(healthFund || '').includes(name))?.[1]
    const prefix = HEALTH_FUND_PREFIXES[formType] || HEALTH_FUND_PREFIXES[matchedFund]
    const numeric = values.length > 0 && values.every((item) => /^\d+(?:[\s./-]\d+)*$/.test(item))
    const valid = numeric && (!prefix || values.every((item) => item.replace(/\D/g, '').startsWith(prefix)))
    return {
      state: valid ? 'green' : 'orange',
      needsReview: !valid,
      signals: { numeric_format: numeric, commitment_prefix_match: valid },
    }
  }
  if (field.key === 'firstName' || field.key === 'lastName') {
    const valid = /^[A-Za-z\u0590-\u05FF][A-Za-z\u0590-\u05FF '’-]{0,79}$/.test(value.trim())
    return {
      state: valid ? 'green' : 'orange',
      needsReview: !valid,
      signals: { field_valid: valid },
    }
  }
  return { state: 'green', needsReview: false }
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
  const metadata = {}
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
      (fieldObject.state !== undefined && fieldObject.state !== 'green') ||
      reviewSet.has(sourceKey) ||
      reviewSet.has(field.key) ||
      (Number.isFinite(confidence) && confidence < (confidence > 1 ? CONFIDENCE_THRESHOLD * 100 : CONFIDENCE_THRESHOLD))

    values[field.key] = value
    uncertain[field.key] = flagged || !value
    metadata[field.key] = {
      state: fieldObject.state || (value ? 'orange' : 'empty'),
      needsReview: flagged || !value,
      confidence: Number.isFinite(confidence) ? confidence : null,
      bbox: Array.isArray(fieldObject.bbox) ? fieldObject.bbox : null,
      handwritten: fieldObject.handwritten === true,
      signals: fieldObject.signals || {},
      raw: fieldObject.raw || null,
    }
  }

  return { values, uncertain, metadata }
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
  const fieldUpdateQueue = useRef(Promise.resolve())
  const [documents, setDocuments] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [pipelineStage, setPipelineStage] = useState('ingestion')
  const [previewId, setPreviewId] = useState(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [selectedField, setSelectedField] = useState(RESULT_FIELDS[0].key)
  const [uploadError, setUploadError] = useState('')
  const [records, setRecords] = useState([])
  const [recordsTotal, setRecordsTotal] = useState(0)
  const [recordsSearch, setRecordsSearch] = useState('')
  const [recordsApproved, setRecordsApproved] = useState('')
  const [recordsOffset, setRecordsOffset] = useState(0)
  const [recordsError, setRecordsError] = useState('')
  const [recordsLoading, setRecordsLoading] = useState(true)
  const [recordsRefresh, setRecordsRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setRecordsLoading(true)
      setRecordsError('')
      const query = new URLSearchParams({ limit: '50', offset: String(recordsOffset) })
      if (recordsSearch.trim()) query.set('search', recordsSearch.trim())
      if (recordsApproved) query.set('approved', recordsApproved)
      try {
        const response = await fetch(`${API_BASE_URL}/api/records?${query}`, {
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('לא ניתן לטעון את הרשומות השמורות.')
        const result = await response.json()
        setRecords(result.records || [])
        setRecordsTotal(result.total || 0)
      } catch (error) {
        if (error.name !== 'AbortError') {
          setRecordsError(error instanceof TypeError
            ? 'לא ניתן להתחבר לשירות. הרשומות השמורות אינן זמינות כרגע.'
            : error.message || 'לא ניתן לטעון את הרשומות השמורות.')
        }
      } finally {
        if (!controller.signal.aborted) setRecordsLoading(false)
      }
    }, 200)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [recordsSearch, recordsApproved, recordsOffset, recordsRefresh])

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
        corrected: {},
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
    const document = documents.find((item) => item.id === id)
    if (!document?.isSavedRecord && document?.documentId && document.status === 'complete') {
      fetch(`${API_BASE_URL}/api/documents/${encodeURIComponent(document.documentId)}?page=${document.page || 1}`, {
        method: 'DELETE',
      }).then((response) => {
        if (!response.ok) setUploadError('לא ניתן למחוק את הטופס מהשרת. נסו שוב.')
      }).catch(() => setUploadError('לא ניתן להתחבר לשירות החילוץ כדי למחוק את הטופס.'))
    }
    setDocuments((current) => current.filter((document) => document.id !== id))
    if (previewId === id) closePreview()
  }

  async function extractDocuments() {
    if (isProcessing) return
    const queue = documents.filter((document) => document.status === 'pending' || document.status === 'error')
    if (!queue.length) return

    setIsProcessing(true)
    setPipelineStage('ingestion')
    setUploadError('')
    setDocuments((current) =>
      current.map((item) =>
        queue.some((queued) => queued.id === item.id)
          ? { ...item, status: 'processing', error: '' }
          : item,
      ),
    )

    try {
      const body = new FormData()
      queue.forEach((document) => body.append('files', document.file))
      const response = await fetch(`${API_BASE_URL}/api/documents/upload`, { method: 'POST', body })
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
      const { batch_id: batchId } = await response.json()
      let batch
      const startedAt = Date.now()
      do {
        await new Promise((resolve) => window.setTimeout(resolve, 1000))
        const statusResponse = await fetch(`${API_BASE_URL}/api/documents/batch/${encodeURIComponent(batchId)}`)
        if (!statusResponse.ok) throw new Error('לא ניתן לקבל את מצב האצווה מהשרת.')
        batch = await statusResponse.json()
        setPipelineStage(batch.stage || 'ingestion')
        if (Date.now() - startedAt > 10 * 60 * 1000) {
          throw new Error('עיבוד הקבצים נמשך זמן רב מדי. אפשר לנסות שוב מאוחר יותר.')
        }
      } while (batch.status === 'queued' || batch.status === 'processing')

      const documentsByName = new Map()
      for (const result of batch.documents || []) {
        const matches = documentsByName.get(result.filename) || []
        matches.push(result)
        documentsByName.set(result.filename, matches)
      }
      const replacements = new Map()
      for (const document of queue) {
        const matches = documentsByName.get(document.file.name) || []
        const result = matches.shift()
        if (!result) {
          replacements.set(document.id, [{
            ...document,
            status: 'error',
            error: 'הקובץ לא הופיע בתוצאות העיבוד.',
          }])
          continue
        }
        if (result.status !== 'complete') {
          replacements.set(document.id, [{
            ...document,
            documentId: result.id,
            status: 'error',
            error: result.error || 'החילוץ נכשל. ניתן לנסות שוב.',
          }])
          continue
        }
        const forms = (result.forms || []).map((form, index) => {
          const page = Number(form.page) || index + 1
          const fieldData = Object.fromEntries(
            (form.fields || []).map((field) => [field.name, field]),
          )
          return {
            ...document,
            id: page === 1 ? document.id : `${document.id}-page-${page}`,
            documentId: result.id,
            batchId,
            page,
            ...normalizeResults({ data: fieldData }),
            formType: form.form_type,
            reviewed: {},
            corrected: {},
            approved: false,
            status: 'complete',
            error: '',
          }
        })
        replacements.set(document.id, forms)
      }
      setDocuments((current) =>
        current.flatMap((item) => replacements.get(item.id) || [item]),
      )
      setRecordsRefresh((current) => current + 1)
      setPipelineStage('complete')
      if (batch.status === 'failed' || batch.status === 'partial') {
        setUploadError('חלק מהקבצים לא עובדו בהצלחה. פרטי השגיאה מוצגים בשורות המתאימות.')
      }
    } catch (requestError) {
      const message = requestError instanceof TypeError
        ? 'לא ניתן להתחבר לשירות החילוץ. בדקו את החיבור ונסו שוב.'
        : requestError.message || 'החילוץ נכשל. נסו שוב בעוד רגע.'
      setDocuments((current) =>
        current.map((item) =>
          queue.some((queued) => queued.id === item.id)
            ? { ...item, status: 'error', error: message }
            : item,
        ),
      )
      setPipelineStage('failed')
    } finally {
    setIsProcessing(false)
    }
  }

  function openPreview(document) {
    setPreviewUrl(document.file instanceof File ? URL.createObjectURL(document.file) : '')
    setPreviewId(document.id)
  }

  function openSavedRecord(record) {
    const fieldData = Object.fromEntries(
      (record.fields || []).map((field) => [field.name, field]),
    )
    const normalized = normalizeResults({ data: fieldData })
    const id = `saved-${record.id}`
    setDocuments((current) => current.some((item) => item.id === id)
      ? current
      : [...current, {
          id,
          isSavedRecord: true,
          file: { name: record.filename, type: 'image/png' },
          documentId: record.document_id,
          batchId: record.batch_id,
          page: record.page,
          formType: record.form_type,
          ...normalized,
          reviewed: {},
          corrected: {},
          approved: record.approved,
          status: 'complete',
          error: '',
        }])
    setPreviewUrl('')
    setPreviewId(id)
  }

  function closePreview() {
    setPreviewId(null)
    setPreviewUrl('')
  }

  function editField(document, field, value) {
    const validation = validateEditedField(field, value, document.formType, document.values.healthFund)
    setDocuments((current) =>
      current.map((item) =>
        item.id === document.id
          ? {
              ...item,
              values: { ...item.values, [field.key]: value },
              uncertain: { ...item.uncertain, [field.key]: validation.needsReview },
              metadata: {
                ...item.metadata,
                [field.key]: {
                  ...item.metadata?.[field.key],
                  ...validation,
                  handwritten: false,
                  confidence: value ? 1 : 0,
                },
              },
              reviewed: { ...item.reviewed, [field.key]: !validation.needsReview },
              corrected: { ...item.corrected, [field.key]: true },
              approved: false,
            }
          : item,
      ),
    )
  }

  async function markFieldReviewed(document, field) {
    try {
      if (document.documentId) {
        if (document.corrected[field.key] && !(await persistField(document, field))) return
        const fieldName = encodeURIComponent(field.aliases[0])
        const update = () => fetch(
          `${API_BASE_URL}/api/documents/${encodeURIComponent(document.documentId)}/fields/${fieldName}/review?page=${document.page || 1}`,
          { method: 'POST' },
        )
        const pending = fieldUpdateQueue.current.catch(() => {}).then(update)
        fieldUpdateQueue.current = pending
        const response = await pending
        if (!response.ok) throw new Error('לא ניתן לשמור את אישור השדה בשרת.')
      }
      setDocuments((current) =>
        current.map((item) =>
          item.id === document.id
              ? {
                  ...item,
                  reviewed: { ...item.reviewed, [field.key]: true },
                  metadata: {
                    ...item.metadata,
                    [field.key]: {
                      ...item.metadata?.[field.key],
                      state: 'green',
                      needsReview: false,
                      confidence: 1,
                    },
                  },
                  approved: false,
                }
              : item,
          ),
      )
      setRecordsRefresh((current) => current + 1)
    } catch (requestError) {
      setUploadError(requestError.message || 'לא ניתן לשמור את בדיקת השדה.')
    }
  }

  async function persistField(document, field) {
    if (!document.documentId || !document.corrected[field.key]) return true
    const value = document.values[field.key] || ''
    const serializedValue = ['centerNumber', 'commitmentNumber'].includes(field.key)
      ? value.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean)
      : value || null
    try {
      const update = () => fetch(
        `${API_BASE_URL}/api/documents/${encodeURIComponent(document.documentId)}/fields`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            page: document.page || 1,
            fields: { [field.aliases[0]]: serializedValue },
          }),
        },
      )
      const pending = fieldUpdateQueue.current.catch(() => {}).then(update)
      fieldUpdateQueue.current = pending
      const response = await pending
      if (!response.ok) throw new Error('לא ניתן לשמור את תיקוני השדה.')
      setRecordsRefresh((current) => current + 1)
      return true
    } catch (requestError) {
      setUploadError(requestError.message || 'לא ניתן לשמור את תיקוני השדה.')
      return false
    }
  }

  async function approveDocument(document) {
    const hasUnreviewedFields = RESULT_FIELDS.some(
      (field) => document.uncertain[field.key] && !document.reviewed[field.key],
    )
    if (hasUnreviewedFields || document.status !== 'complete') return false
    try {
      if (document.documentId) {
        const correctedFields = Object.fromEntries(
          RESULT_FIELDS
            .filter((field) => document.corrected[field.key] && !document.reviewed[field.key])
            .map((field) => [
              field.aliases[0],
              ['centerNumber', 'commitmentNumber'].includes(field.key)
                ? document.values[field.key].split(/[,;\n]+/).map((value) => value.trim()).filter(Boolean)
                : document.values[field.key] || null,
            ]),
        )
        if (Object.keys(correctedFields).length) {
          await fieldUpdateQueue.current.catch(() => {})
          const response = await fetch(
            `${API_BASE_URL}/api/documents/${encodeURIComponent(document.documentId)}/fields`,
            {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ page: document.page || 1, fields: correctedFields }),
            },
          )
          if (!response.ok) throw new Error('לא ניתן לשמור את תיקוני הטופס.')
        }
        const response = await fetch(
          `${API_BASE_URL}/api/documents/${encodeURIComponent(document.documentId)}/approve?page=${document.page || 1}`,
          { method: 'POST' },
        )
        if (!response.ok) throw new Error('השרת דחה את אישור הטופס. בדקו שכל השדות סומנו.')
      }
      updateDocument(document.id, { approved: true })
      setDocuments((current) => current.map((item) => item.id === document.id
        ? { ...item, metadata: Object.fromEntries(Object.entries(item.metadata || {}).map(([key, meta]) => [
            key,
            { ...meta, state: 'green', needsReview: false },
          ])) }
        : item))
      setRecordsRefresh((current) => current + 1)
      return true
    } catch (requestError) {
      setUploadError(requestError.message || 'לא ניתן לאשר את הטופס.')
      return false
    }
  }

  async function exportApprovedDocuments() {
    const approved = documents.filter((document) => document.approved)
    if (!approved.length) return

    setIsExporting(true)
    setUploadError('')
    try {
      const documentIds = [...new Set(approved.map((document) => document.documentId).filter(Boolean))]
      if (documentIds.length && approved.every((document) => document.documentId)) {
        const query = new URLSearchParams()
        documentIds.forEach((documentId) => query.append('document_ids', documentId))
        const response = await fetch(`${API_BASE_URL}/api/export.xlsx?${query}`)
        if (!response.ok) throw new Error('ייצוא הטפסים שאושרו מהשרת נכשל.')
        downloadBlob(await response.blob(), 'טפסים-מאושרים.xlsx')
      } else {
        const rows = approved.flatMap((document) => {
          const commitments = document.values.commitmentNumber
            .split(/[,;\n]+/)
            .map((value) => value.trim())
            .filter(Boolean)
          return (commitments.length ? commitments : ['']).map((commitment) => ({
            'שם הקובץ': document.file.name,
            'עמוד': document.page || '',
            'סוג טופס': document.formType || '',
            ...Object.fromEntries(RESULT_FIELDS.map((field) => [
              field.label,
              field.key === 'commitmentNumber'
                ? commitment
                : document.values[field.key] || '',
            ])),
          }))
        })
        await downloadSpreadsheet(rows, 'טפסים-מאושרים.xlsx')
      }
    } catch (exportError) {
      setUploadError(`ייצוא לאקסל נכשל: ${exportError.message || 'נסו שוב.'}`)
    } finally {
      setIsExporting(false)
    }
  }

  async function exportSavedRecords() {
    setIsExporting(true)
    setUploadError('')
    try {
      const approvedRecords = []
      let offset = 0
      let total = 0
      do {
        const query = new URLSearchParams({
          approved: 'true',
          limit: '200',
          offset: String(offset),
        })
        const response = await fetch(`${API_BASE_URL}/api/records?${query}`)
        if (!response.ok) throw new Error('לא ניתן לטעון את כל הרשומות שאושרו לייצוא.')
        const result = await response.json()
        approvedRecords.push(...(result.records || []))
        total = Number(result.total) || 0
        offset += 200
      } while (offset < total && offset > 0)

      if (!approvedRecords.length) throw new Error('לא נמצאו רשומות מאושרות לייצוא.')
      const documentIds = [...new Set(approvedRecords.map((record) => record.document_id).filter(Boolean))]
      if (documentIds.length && approvedRecords.every((record) => record.document_id)) {
        const exportQuery = new URLSearchParams()
        documentIds.forEach((documentId) => exportQuery.append('document_ids', documentId))
        const response = await fetch(`${API_BASE_URL}/api/export.xlsx?${exportQuery}`)
        if (!response.ok) throw new Error('ייצוא הרשומות המאושרות נכשל.')
        downloadBlob(await response.blob(), 'טפסים-מאושרים.xlsx')
      } else {
        const rows = approvedRecords.flatMap((record) => {
          const values = Object.fromEntries((record.fields || []).map((field) => [field.name, field.value]))
          const commitments = values.commitment_number
          const commitmentList = Array.isArray(commitments)
            ? commitments.map(String).filter(Boolean)
            : getFieldValue(commitments).split(/[,;\n]+/).map((value) => value.trim()).filter(Boolean)
          return (commitmentList.length ? commitmentList : ['']).map((commitment) => ({
            'שם הקובץ': record.filename,
            'עמוד': record.page || '',
            'סוג טופס': record.form_type || '',
            ...Object.fromEntries(RESULT_FIELDS.map((field) => [
              field.label,
              field.key === 'commitmentNumber'
                ? commitment
                : getFieldValue(values[field.aliases[0]]),
            ])),
          }))
        })
        await downloadSpreadsheet(rows, 'טפסים-מאושרים.xlsx')
      }
    } catch (error) {
      setUploadError(error.message || 'לא ניתן לייצא את הרשומות.')
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#f4f8f8]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-gradient-to-b from-[#e5f3f3] via-[#f0f7f7] to-transparent" />

      <header className="relative border-b border-slate-200/80 bg-white/70">
        <div className="mx-auto flex h-[76px] max-w-7xl items-center justify-between px-5 sm:px-8">
          <a href="#" className="flex items-center gap-3" aria-label="MedExtract - דף הבית">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#e5f3f3] text-[#007c86]">
              <HeartPulse size={22} strokeWidth={2.2} />
            </span>
            <span className="text-[17px] font-extrabold tracking-tight text-[#15324e]">
              Med<span className="text-[#008c95]">Extract</span>
            </span>
          </a>
          <div className="hidden items-center gap-2 rounded-full border border-[#d7e8e8] bg-white px-3.5 py-2 text-xs font-medium text-slate-500 sm:flex">
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
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#d2e8e7] bg-white/80 px-3.5 py-1.5 text-xs font-semibold text-[#007c86] shadow-sm">
            <Sparkles size={14} />
            חילוץ ובדיקת מסמכים רפואיים
          </div>
          <h1 className="text-3xl font-extrabold leading-tight tracking-tight text-[#173a4a] sm:text-[42px]">
            טפסים מסודרים,
            <span className="text-[#008c95]"> בלי הקלדה מיותרת</span>
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-[15px] leading-7 text-slate-500 sm:text-base">
            העלו כמה טפסים יחד, בדקו שדות לא ודאיים, ערכו ואשרו לפני הייצוא לאקסל.
          </p>
        </section>

        <section className="mx-auto mt-9 max-w-4xl overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card sm:mt-11">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 sm:px-7">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#edf6f5] text-[#00828a]">
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
                  ? 'border-[#008c95] bg-[#e8f5f4]'
                  : 'border-[#d4e4e3] bg-[#fbfdfd] hover:border-[#81bfc0] hover:bg-[#f4f9f8]'
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
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#e8f5f4] text-[#008c95] transition-transform group-hover:-translate-y-0.5">
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
                קובצי המקור נמחקים לאחר העיבוד; הרשומות נשמרות במערכת.
              </p>
              <button
                type="button"
                disabled={!pendingCount || isProcessing}
                onClick={extractDocuments}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#008c95] px-6 py-3 text-sm font-bold text-white shadow-sm shadow-[#008c95]/20 transition hover:bg-[#006f78] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none sm:w-auto"
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
            {isProcessing && (
              <div className="mt-5 border-t border-slate-100 pt-5">
                <LivePipelineStepper activeStage={pipelineStage} />
              </div>
            )}
          </div>
        </section>

        {documents.length > 0 && (
          <section id="batch-history" className="mx-auto mt-6 max-w-7xl overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-7">
              <div>
                <h2 className="text-base font-bold text-slate-800">תוצאות חילוץ</h2>
                <p className="mt-1 text-xs text-slate-400">
                  {documents.length} טפסים · {approvedCount} אושרו
                </p>
              </div>
              {approvedCount > 0 && (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-xs text-slate-500">הייצוא כולל רק טפסים שאושרו ({approvedCount})</span>
                  <button
                    type="button"
                    disabled={isExporting}
                    onClick={exportApprovedDocuments}
                    className="flex items-center gap-2 rounded-lg bg-[#008c95] px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#006f78] disabled:cursor-wait disabled:opacity-60"
                  >
                    {isExporting ? <LoaderCircle size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}
                    {isExporting ? 'מייצא...' : `ייצוא ${approvedCount} טפסים שאושרו`}
                  </button>
                </div>
              )}
            </div>

            <div className="grid gap-4 bg-slate-50/60 p-4 sm:grid-cols-2 sm:p-6 xl:grid-cols-3">
              {documents.map((document, index) => {
                const needsReview = RESULT_FIELDS.filter(
                  (field) => document.uncertain[field.key] && !document.reviewed[field.key],
                )
                const found = RESULT_FIELDS.filter((field) => document.values[field.key]).length
                const status = document.status === 'processing'
                  ? ['בעיבוד', 'border-teal-200 bg-teal-50 text-teal-800']
                  : document.status === 'error'
                    ? ['נדרש ניסיון נוסף', 'border-rose-200 bg-rose-50 text-rose-700']
                    : document.approved
                      ? ['אושר', 'border-emerald-200 bg-emerald-50 text-emerald-700']
                      : document.status === 'pending'
                        ? ['ממתין לחילוץ', 'border-slate-200 bg-white text-slate-500']
                        : needsReview.length
                          ? ['נדרשת בדיקה', 'border-amber-200 bg-amber-50 text-amber-800']
                          : ['מוכן לאישור', 'border-teal-200 bg-teal-50 text-teal-800']
                const visibleFields = RESULT_FIELDS.filter(
                  (field) => document.values[field.key] || document.uncertain[field.key],
                )
                return (
                  <article key={document.id} className="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-card">
                    <button
                      type="button"
                      disabled={document.status !== 'complete'}
                      onClick={() => openPreview(document)}
                      aria-label={`פתיחת פרטי ${document.file.name}`}
                      className="block w-full p-5 text-right disabled:cursor-default"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-teal-50 text-teal-800">
                            {document.file.type === 'application/pdf' ? <FileText size={20} /> : <FileImage size={20} />}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-bold text-slate-800" title={document.file.name}>{document.file.name}</span>
                            <span className="mt-1 block text-xs text-slate-400">
                              קובץ {index + 1}{document.page ? ` · עמוד ${document.page}` : ''}
                              {document.file.size ? ` · ${formatFileSize(document.file.size)}` : ''}
                            </span>
                          </span>
                        </div>
                        <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${status[1]}`}>
                          {document.status === 'processing' && <LoaderCircle size={12} className="ml-1 inline animate-spin" />}
                          {status[0]}
                        </span>
                      </div>
                      {document.status === 'complete' ? (
                        <>
                          <div className="mt-5 flex items-center justify-between text-xs">
                            <span className="font-semibold text-slate-600">מצב השדות</span>
                            <span className="text-slate-500">{found} מתוך {RESULT_FIELDS.length} זוהו</span>
                          </div>
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                            <div className={`h-full rounded-full ${needsReview.length ? 'bg-amber-400' : 'bg-emerald-500'}`} style={{ width: `${(found / RESULT_FIELDS.length) * 100}%` }} />
                          </div>
                          <div className="mt-4 flex items-center gap-2 text-xs">
                            {needsReview.length ? (
                              <span className="flex items-center gap-1.5 font-semibold text-amber-800"><AlertCircle size={14} /> {needsReview.length} שדות דורשים בדיקה</span>
                            ) : (
                              <span className="flex items-center gap-1.5 font-semibold text-emerald-700"><CheckCircle2 size={14} /> אין שדות הממתינים לבדיקה</span>
                            )}
                          </div>
                          <div className="mt-4 space-y-2 border-t border-slate-100 pt-3">
                            {visibleFields.slice(0, 3).map((field) => {
                              const review = document.uncertain[field.key] && !document.reviewed[field.key]
                              return (
                                <div key={field.key} className="flex items-center justify-between gap-3 text-xs">
                                  <span className="shrink-0 text-slate-400">{field.label}</span>
                                  <span className={`truncate rounded-md px-2 py-1 ${review ? 'bg-amber-50 font-semibold text-amber-800' : document.values[field.key] ? 'text-slate-700' : 'text-slate-400'}`}>
                                    {document.values[field.key] || 'לא זוהה'}{review ? ' · לבדיקה' : ''}
                                  </span>
                                </div>
                              )
                            })}
                            {visibleFields.length > 3 && <span className="block pt-1 text-[11px] text-teal-800">ועוד שדות — לחצו לצפייה בפרטים</span>}
                          </div>
                          <span className="mt-5 flex items-center justify-center gap-2 rounded-lg bg-teal-50 px-3 py-2.5 text-sm font-bold text-teal-800 transition group-hover:bg-teal-100">
                            <Eye size={16} /> פתיחת הפרטים לבדיקה
                          </span>
                        </>
                      ) : (
                        <div className="mt-5 rounded-lg bg-slate-50 px-3 py-3 text-xs leading-5 text-slate-500">
                          {document.status === 'processing' && 'המסמך בעיבוד. התוצאות יופיעו כאן בסיום.'}
                          {document.status === 'pending' && `מוכן לעיבוד${document.file.size ? ` · ${formatFileSize(document.file.size)}` : ''}`}
                          {document.status === 'error' && (document.error || 'החילוץ לא הצליח. אפשר לנסות שוב.')}
                        </div>
                      )}
                    </button>
                    <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5">
                      <span className="text-[11px] text-slate-400">
                        {document.approved ? 'נכלל בייצוא המאושרים' : document.status === 'complete' ? 'אישור נדרש לפני ייצוא' : ' '}
                      </span>
                      <div className="flex items-center gap-1">
                        {document.status === 'error' && (
                          <button type="button" onClick={extractDocuments} className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold text-teal-800 hover:bg-teal-50">
                            <RotateCcw size={13} /> נסו שוב
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => removeDocument(document.id)}
                          aria-label={`הסרת ${document.file.name}`}
                          className="rounded-md p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                        >
                          <X size={15} />
                        </button>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
            <div hidden aria-hidden="true">
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
                              ? <FileText size={16} className="mt-0.5 shrink-0 text-[#008c95]" />
                              : <FileImage size={16} className="mt-0.5 shrink-0 text-[#008c95]" />}
                            <div className="min-w-0">
                              <span className="block text-xs text-slate-400">טופס {index + 1}</span>
                              <span className="mt-1 block truncate font-semibold text-slate-700" title={document.file.name}>
                                {document.file.name}{document.page ? ` · עמוד ${document.page}` : ''}
                              </span>
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
                          {document.status === 'processing' && <span className="flex items-center gap-1.5 text-xs text-teal-700"><LoaderCircle size={14} className="animate-spin" /> בעיבוד</span>}
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
                                className="flex items-center gap-1 rounded-md px-2.5 py-2 text-xs font-semibold text-[#007c86] hover:bg-[#edf6f5]"
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
                              <button type="button" onClick={extractDocuments} className="rounded-md px-2.5 py-2 text-xs font-semibold text-[#007c86] hover:bg-[#edf6f5]">
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

        <section className="mx-auto mt-6 max-w-7xl overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-5 py-4 sm:px-7">
            <div>
              <h2 className="text-base font-bold text-slate-800">היסטוריית אצוות ורשומות שמורות</h2>
              <p className="mt-1 text-xs text-slate-400">
                {recordsLoading ? 'טוען רשומות...' : `${recordsTotal} רשומות במערכת`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="relative">
                <Search size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="search"
                  value={recordsSearch}
                  onChange={(event) => {
                    setRecordsOffset(0)
                    setRecordsSearch(event.target.value)
                  }}
                  placeholder="חיפוש בשם, ת.ז. או מספר"
                  aria-label="חיפוש ברשומות השמורות"
                  className="w-60 rounded-lg border border-slate-200 py-2.5 pr-9 pl-3 text-sm outline-none focus:border-[#008c95] focus:ring-2 focus:ring-[#e4f3f2]"
                />
              </label>
              <select
                value={recordsApproved}
                onChange={(event) => {
                  setRecordsOffset(0)
                  setRecordsApproved(event.target.value)
                }}
                aria-label="סינון לפי אישור"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-600 outline-none focus:border-[#008c95]"
              >
                <option value="">כל סטטוסי האישור</option>
                <option value="true">אושרו</option>
                <option value="false">ממתינים לאישור</option>
              </select>
              {recordsApproved === 'true' && recordsTotal > 0 && (
                <button
                  type="button"
                  disabled={isExporting}
                  onClick={exportSavedRecords}
                  className="flex items-center gap-2 rounded-lg bg-[#008c95] px-3 py-2.5 text-sm font-bold text-white transition hover:bg-[#006f78] disabled:cursor-wait disabled:opacity-60"
                >
                  {isExporting ? <LoaderCircle size={15} className="animate-spin" /> : <FileSpreadsheet size={15} />}
                  {isExporting ? 'מייצא...' : 'ייצוא כל המאושרים'}
                </button>
              )}
            </div>
          </div>
          {recordsError && (
            <p role="alert" className="px-5 py-3 text-sm text-rose-700 sm:px-7">{recordsError}</p>
          )}
          {recordsLoading && <p className="px-5 py-8 text-center text-sm text-slate-500">טוען רשומות…</p>}
          {!recordsLoading && !recordsError && records.length === 0 && (
            <p className="px-5 py-10 text-center text-sm text-slate-500">לא נמצאו רשומות מתאימות.</p>
          )}
          <div className="grid gap-4 bg-slate-50/60 p-4 sm:grid-cols-2 sm:p-6 xl:grid-cols-3">
            {records.map((record) => {
              const values = Object.fromEntries((record.fields || []).map((field) => [field.name, field.value]))
              const needsReview = (record.fields || []).filter((field) => field.needs_review).length
              const visibleFields = RESULT_FIELDS.filter((field) => getFieldValue(values[field.aliases[0]]))
              return (
                <button
                  type="button"
                  key={record.id}
                  onClick={() => openSavedRecord(record)}
                  className="group rounded-2xl border border-slate-200 bg-white p-5 text-right shadow-sm transition hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-card"
                >
                  <span className="flex items-start justify-between gap-3">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-bold text-slate-800" title={record.filename}>{record.filename}</span>
                      <span className="mt-1 block text-xs text-slate-400">{record.form_type || 'סוג טופס לא ידוע'} · עמוד {record.page}</span>
                    </span>
                    <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                      record.approved
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : needsReview
                          ? 'border-amber-200 bg-amber-50 text-amber-800'
                          : 'border-teal-200 bg-teal-50 text-teal-800'
                    }`}>
                      {record.approved ? 'אושר' : needsReview ? `${needsReview} לבדיקה` : 'ממתין לאישור'}
                    </span>
                  </span>
                  <span className="mt-4 block space-y-2 border-t border-slate-100 pt-3">
                    {visibleFields.slice(0, 3).map((field) => {
                      const item = (record.fields || []).find((candidate) => candidate.name === field.aliases[0])
                      return (
                        <span key={field.key} className="flex items-center justify-between gap-3 text-xs">
                          <span className="shrink-0 text-slate-400">{field.label}</span>
                          <span className={`truncate rounded-md px-2 py-1 ${item?.needs_review ? 'bg-amber-50 font-semibold text-amber-800' : 'text-slate-700'}`}>
                            {getFieldValue(values[field.aliases[0]])}
                          </span>
                        </span>
                      )
                    })}
                    {visibleFields.length > 3 && <span className="block pt-1 text-[11px] text-teal-800">ועוד שדות — לחצו לצפייה בפרטים</span>}
                  </span>
                  <span className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-[11px] text-slate-400">
                    <span>{record.created_at ? new Date(record.created_at).toLocaleDateString('he-IL') : ''}</span>
                    <span className="font-semibold text-teal-800 group-hover:text-teal-950">פתיחת פרטים לבדיקה ←</span>
                  </span>
                </button>
              )
            })}
          </div>
          <div hidden aria-hidden="true">
            <table className="w-full min-w-[1200px] border-collapse text-right text-sm">
              <thead className="bg-slate-50 text-xs font-semibold text-slate-500">
                <tr>
                  <th className="px-4 py-3">קובץ / עמוד</th>
                  {RESULT_FIELDS.map((field) => <th key={field.key} className="px-4 py-3">{field.label}</th>)}
                  <th className="px-4 py-3">סטטוס</th>
                  <th className="px-4 py-3">נוצר</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {records.map((record) => {
                  const values = Object.fromEntries((record.fields || []).map((field) => [field.name, field.value]))
                  return (
                    <tr key={record.id} className="align-top hover:bg-slate-50/60">
                      <td className="max-w-[220px] px-4 py-3">
                        <button
                          type="button"
                          onClick={() => openSavedRecord(record)}
                          className="block max-w-full truncate text-right font-semibold text-teal-800 hover:underline"
                          title={`פתיחת ${record.filename}`}
                        >
                          {record.filename}
                        </button>
                        <span className="text-xs text-slate-400">{record.form_type} · עמוד {record.page}</span>
                      </td>
                      {RESULT_FIELDS.map((field) => {
                        const value = getFieldValue(values[field.aliases[0]])
                        const item = (record.fields || []).find((candidate) => candidate.name === field.aliases[0])
                        return (
                          <td key={field.key} className="px-4 py-3">
                            <span className={`inline-block max-w-[160px] truncate rounded px-1.5 py-1 ${item?.needs_review ? 'bg-amber-100 text-amber-800' : 'text-slate-700'}`} title={value}>
                              {value || (item?.needs_review ? 'לא בטוח — בדקי' : '—')}
                            </span>
                          </td>
                        )
                      })}
                      <td className="whitespace-nowrap px-4 py-3">
                        {record.approved
                          ? <span className="flex items-center gap-1 text-xs font-semibold text-emerald-700"><CheckCircle2 size={14} /> אושר</span>
                          : <span className="text-xs text-amber-700">ממתין לבדיקה</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                        {record.created_at ? new Date(record.created_at).toLocaleDateString('he-IL') : '—'}
                      </td>
                    </tr>
                  )
                })}
                {!recordsLoading && !recordsError && records.length === 0 && (
                  <tr><td colSpan={RESULT_FIELDS.length + 3} className="px-4 py-10 text-center text-sm text-slate-400">לא נמצאו רשומות מתאימות.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-xs text-slate-500 sm:px-7">
            <span>
              {recordsTotal
                ? `מציגות ${recordsOffset + 1}–${Math.min(recordsOffset + records.length, recordsTotal)} מתוך ${recordsTotal}`
                : 'אין רשומות להצגה'}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!recordsOffset || recordsLoading}
                onClick={() => setRecordsOffset((current) => Math.max(0, current - 50))}
                className="rounded-md border border-slate-200 px-3 py-1.5 disabled:opacity-40"
              >
                הקודמות
              </button>
              <button
                type="button"
                disabled={recordsOffset + records.length >= recordsTotal || recordsLoading}
                onClick={() => setRecordsOffset((current) => current + 50)}
                className="rounded-md border border-slate-200 px-3 py-1.5 disabled:opacity-40"
              >
                הבאות
              </button>
            </div>
          </div>
        </section>

        <footer className="mx-auto mt-8 flex max-w-4xl items-center justify-center gap-2 text-xs text-slate-400">
          <ShieldCheck size={15} className="text-[#008c95]" />
          המידע מוצג למטרת עיבוד המסמך בלבד
        </footer>
      </main>

      {previewDocument && (previewUrl || previewDocument.documentId) && (
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
                <p className="mt-1 truncate text-xs text-slate-400">
                  {previewDocument.file.name}{previewDocument.page ? ` · עמוד ${previewDocument.page}` : ''}
                </p>
              </div>
              <button type="button" onClick={closePreview} aria-label="סגירה" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100">
                <X size={20} />
              </button>
            </header>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-2 lg:overflow-hidden">
              <DocumentViewer
                fallbackUrl={previewUrl}
                fileName={previewDocument.file.name}
                fileType={previewDocument.file.type}
                documentId={previewDocument.documentId}
                page={previewDocument.page}
                selectedField={selectedField}
                fields={previewDocument.metadata || {}}
                onSelectField={setSelectedField}
              />

              <div className="min-h-0 overflow-y-auto">
                <ExtractedDataForm
                  fields={RESULT_FIELDS}
                  values={previewDocument.values}
                  metadata={previewDocument.metadata || {}}
                  selectedField={selectedField}
                  reviewed={previewDocument.reviewed}
                  onSelectField={setSelectedField}
                  onChange={(field, value) => editField(previewDocument, field, value)}
                  onBlur={(field) => persistField(previewDocument, field)}
                  onMarkReviewed={(field) => markFieldReviewed(previewDocument, field)}
                />
                <div className="sticky bottom-0 mt-5 flex items-center justify-between gap-3 border-t border-slate-100 bg-white py-4">
                  <span className="text-xs text-slate-400">
                    {RESULT_FIELDS.filter((field) => previewDocument.uncertain[field.key] && !previewDocument.reviewed[field.key]).length
                      ? 'נותרו שדות לבדיקה'
                      : 'כל השדות הלא ודאיים נבדקו'}
                  </span>
                  <button
                    type="button"
                    disabled={RESULT_FIELDS.some((field) => previewDocument.uncertain[field.key] && !previewDocument.reviewed[field.key])}
                    onClick={async () => {
                      const approved = await approveDocument(previewDocument)
                      if (approved) closePreview()
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
