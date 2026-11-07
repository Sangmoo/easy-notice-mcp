/** 업로드 파일 → Claude 입력 블록 (두 프로젝트 공통). 브라우저 안에서만 처리한다. */
import type { ContentBlock } from './claude'
import { ToolError } from './errors'

export const MAX_SIDE = 1568 // 이 이상은 Claude가 내부적으로 축소하므로 미리 줄여 전송량/비용 절감
const MAX_PDF_BYTES = 32 * 1024 * 1024

export function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return btoa(bin)
}

async function imageBlock(file: File): Promise<ContentBlock> {
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    throw new ToolError(`'${file.name}'을(를) 읽을 수 없습니다. JPG·PNG·WEBP로 변환해 주세요 (아이폰 HEIC는 미지원).`)
  }
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
  const w = Math.max(1, Math.round(bitmap.width * scale))
  const h = Math.max(1, Math.round(bitmap.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#fff' // 투명 PNG 배경
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(bitmap, 0, 0, w, h)
  bitmap.close()
  const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/jpeg', 0.85))
  if (!blob) throw new ToolError(`'${file.name}' 변환에 실패했습니다.`)
  return {
    type: 'image',
    source: { type: 'base64', media_type: 'image/jpeg', data: bytesToBase64(new Uint8Array(await blob.arrayBuffer())) },
  }
}

async function pdfBlock(file: File): Promise<ContentBlock> {
  if (file.size > MAX_PDF_BYTES) throw new ToolError(`'${file.name}'이(가) 너무 큽니다 (32MB 초과).`)
  return {
    type: 'document',
    source: { type: 'base64', media_type: 'application/pdf', data: bytesToBase64(new Uint8Array(await file.arrayBuffer())) },
  }
}

export async function fileToBlock(file: File, allowPdf = true): Promise<ContentBlock> {
  if (isPdf(file)) {
    if (!allowPdf) throw new ToolError('PDF는 지원하지 않습니다. 사진 파일을 넣어주세요.')
    return pdfBlock(file)
  }
  return imageBlock(file)
}
