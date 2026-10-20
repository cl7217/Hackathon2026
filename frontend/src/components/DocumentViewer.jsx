import { useEffect, useMemo, useState } from 'react'

const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')

async function createCrop(source, bbox, naturalWidth, naturalHeight) {
  if (!bbox || bbox.length !== 4 || !naturalWidth || !naturalHeight) return ''
  const [left, top, right, bottom] = bbox.map(Number)
  if (left < 0 || top < 0 || right > naturalWidth || bottom > naturalHeight || right <= left || bottom <= top) {
    return ''
  }
  const image = new Image()
  image.crossOrigin = 'anonymous'
  return new Promise((resolve) => {
    image.onload = () => {
      const canvas = window.document.createElement('canvas')
      canvas.width = Math.max(1, right - left)
      canvas.height = Math.max(1, bottom - top)
      const context = canvas.getContext('2d')
      context.drawImage(image, left, top, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height)
      resolve(canvas.toDataURL('image/png'))
    }
    image.onerror = () => resolve('')
    image.src = source
  })
}

export default function DocumentViewer({
  fallbackUrl,
  fileName,
  documentId,
  page,
  fileType,
  selectedField,
  fields,
  onSelectField,
}) {
  const [pageImageUrl, setPageImageUrl] = useState('')
  const selectedMeta = fields[selectedField]
  const imageUrl = pageImageUrl || (fallbackUrl && fileType !== 'application/pdf' ? fallbackUrl : '')
  const [cropUrl, setCropUrl] = useState('')
  const bbox = selectedMeta?.bbox
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 })
  const zoomOrigin = bbox && naturalSize.width && naturalSize.height
    ? `${((bbox[0] + bbox[2]) / (2 * naturalSize.width)) * 100}% ${((bbox[1] + bbox[3]) / (2 * naturalSize.height)) * 100}%`
    : 'center'

  useEffect(() => {
    setPageImageUrl('')
    setNaturalSize({ width: 0, height: 0 })
    if (!documentId) return undefined
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/pages/${page || 1}/image`, {
      signal: controller.signal,
    }).then((response) => {
      if (!response.ok) return ''
      return response.blob().then((blob) => URL.createObjectURL(blob))
    }).then((url) => {
      if (url && !controller.signal.aborted) setPageImageUrl(url)
      else if (url) URL.revokeObjectURL(url)
    }).catch((error) => {
      if (error.name !== 'AbortError') setPageImageUrl('')
    })
    return () => controller.abort()
  }, [documentId, page])

  useEffect(() => () => {
    if (pageImageUrl) URL.revokeObjectURL(pageImageUrl)
  }, [pageImageUrl])

  useEffect(() => {
    let disposed = false
    if (!imageUrl || !bbox || !naturalSize.width || !naturalSize.height || !selectedMeta?.handwritten) {
      setCropUrl('')
      return undefined
    }
    createCrop(imageUrl, bbox, naturalSize.width, naturalSize.height).then((url) => {
      if (!disposed) setCropUrl(url)
    })
    return () => {
      disposed = true
    }
  }, [imageUrl, bbox, naturalSize, selectedMeta?.handwritten])

  const boxes = useMemo(
    () => Object.entries(fields).filter(([, metadata]) => metadata?.bbox),
    [fields],
  )

  return (
    <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 bg-slate-100 p-3 lg:min-h-0">
      {imageUrl ? (
        <div className="flex h-[60vh] w-full items-center justify-center overflow-hidden">
          <div
            className="relative inline-block max-h-[60vh] max-w-full transition-transform duration-300"
            style={{ transform: bbox ? 'scale(1.6)' : undefined, transformOrigin: zoomOrigin }}
          >
            <img
              src={imageUrl}
              alt={`סריקת ${fileName}, עמוד ${page || 1}`}
              className="block max-h-[60vh] max-w-full rounded-lg object-contain shadow-sm"
              onLoad={(event) => setNaturalSize({
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              })}
            />
            {naturalSize.width > 0 && (
              <svg
                viewBox={`0 0 ${naturalSize.width} ${naturalSize.height}`}
                preserveAspectRatio="none"
                className="pointer-events-none absolute inset-0 h-full w-full"
                aria-label="מיקומי שדות שחולצו"
              >
                {boxes.map(([fieldKey, metadata]) => {
                  const [x, y, right, bottom] = metadata.bbox
                  const selected = fieldKey === selectedField
                  return (
                    <g key={fieldKey} className="pointer-events-auto cursor-pointer" onClick={() => onSelectField(fieldKey)}>
                      <rect
                        x={x}
                        y={y}
                        width={right - x}
                        height={bottom - y}
                        fill={selected ? 'rgba(0, 140, 149, 0.18)' : 'rgba(0, 124, 134, 0.08)'}
                        stroke={selected ? '#008c95' : '#007c86'}
                        strokeWidth={selected ? 5 : 3}
                      />
                    </g>
                  )
                })}
              </svg>
            )}
          </div>
        </div>
      ) : fallbackUrl && fileType === 'application/pdf' ? (
        <iframe
          title={`תצוגת ${fileName}`}
          src={`${fallbackUrl}#page=${page || 1}`}
          className="h-[60vh] w-full rounded-lg bg-white"
        />
      ) : fallbackUrl ? (
        <img src={fallbackUrl} alt={`תצוגת ${fileName}`} className="max-h-[60vh] max-w-full rounded-lg object-contain" />
      ) : (
        <p className="text-sm text-slate-500">תצוגת המסמך אינה זמינה. ניתן לפתוח שוב את הקובץ לאחר עיבוד.</p>
      )}
      {selectedMeta?.handwritten && cropUrl && (
        <figure className="w-full rounded-lg border border-teal-200 bg-white p-2">
          <figcaption className="mb-1 text-xs font-semibold text-teal-800">חיתוך מוגדל · {selectedField}</figcaption>
          <img src={cropUrl} alt={`הגדלה של ${selectedField}`} className="mx-auto max-h-36 max-w-full object-contain" />
        </figure>
      )}
      <p className="text-center text-xs text-slate-500">לחצו על מסגרת כדי לבחור שדה. המסגרות מסומנות לפי מיקום החילוץ.</p>
    </div>
  )
}
