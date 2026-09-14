import {once} from 'node:events'
import type {IncomingMessage, ServerResponse} from 'node:http'
import {context, media, reddit, redis} from '@devvit/web/server'
import {RichTextBuilder} from '@devvit/reddit'
import type {
  PartialJsonValue,
  TaskResponse,
  TriggerResponse,
  UiResponse,
} from '@devvit/web/shared'
import {
  Endpoint,
  EndpointMethod,
  type ErrorRsp,
  type GetCounterRsp,
  type IncCounterReq,
  type IncCounterRsp,
} from '../shared/api.ts'
import {dbGetCounter, dbIncCounter} from './db.ts'

type AnyRsp =
  | GetCounterRsp
  | IncCounterRsp
  | UiResponse
  | TriggerResponse
  | TaskResponse
  | ErrorRsp

const GITHUB_WALLPAPERS_API =
  'https://api.github.com/repos/kevmio29-arch/tmdb-france-wallpapers/contents/wallpapers?ref=main'

export async function onReq(
  reqMsg: IncomingMessage,
  rspMsg: ServerResponse,
): Promise<void> {
  try {
    await route(reqMsg, rspMsg)
  } catch (err) {
    const msg = `server error; ${err instanceof Error ? err.stack : err}`
    console.error(msg)
    writeJson<ErrorRsp>(500, {error: msg, status: 500}, rspMsg)
  }
}

async function route(
  reqMsg: IncomingMessage,
  rspMsg: ServerResponse,
): Promise<void> {
  const endpoint = reqMsg.url?.slice(1) as Endpoint
  const method = EndpointMethod[endpoint]

  let rsp: AnyRsp
  if (method !== reqMsg.method) {
    rsp = {error: 'not found', status: 404}
  } else {
    switch (endpoint) {
      case Endpoint.GetCounter:
        rsp = await routeGetCounter()
        break
      case Endpoint.IncCounter:
        rsp = await routeInc(reqMsg)
        break
      case Endpoint.OnMenuNewPost:
        rsp = await routeMenuNewPost()
        break
      case Endpoint.OnSchedulerPublish:
        rsp = await routeSchedulerPublish()
        break
      case Endpoint.OnAppInstall:
        rsp = await routeAppInstall()
        break
      default:
        endpoint satisfies never
        rsp = {error: 'not found', status: 404}
        break
    }
  }

  writeJson<PartialJsonValue>('status' in rsp ? rsp.status : 200, rsp, rspMsg)
}

async function routeGetCounter(): Promise<GetCounterRsp> {
  const t3 = context.postId
  if (!t3) throw Error('no t3')
  return {count: await dbGetCounter(t3)}
}

async function routeInc(reqMsg: IncomingMessage): Promise<IncCounterRsp> {
  const t3 = context.postId
  if (!t3) throw Error('no t3')
  const req = await readJson<IncCounterReq>(reqMsg)
  return {count: await dbIncCounter(t3, req.amount)}
}

async function routeMenuNewPost(): Promise<UiResponse> {
  const result = await publishNextWallpaper()
  return {
    showToast: {text: `Wallpaper publié : ${result.title}`, appearance: 'success'},
    navigateTo: result.url,
  }
}

async function routeSchedulerPublish(): Promise<TaskResponse> {
  await publishNextWallpaper()
  return {status: 'ok'}
}

async function publishNextWallpaper(): Promise<{title: string; url: string}> {
  const response = await fetch(GITHUB_WALLPAPERS_API, {
    headers: {Accept: 'application/vnd.github+json'},
  })
  if (!response.ok) {
    throw Error(`GitHub wallpapers request failed: ${response.status}`)
  }

  const files = (await response.json()) as Array<{name: string; type: string}>
  const wallpapers = files
    .filter((file) => file.type === 'file' && file.name.toLowerCase().endsWith('.jpg'))
    .map((file) => file.name)
    .sort((a, b) => a.localeCompare(b, 'fr'))

  if (wallpapers.length === 0) throw Error('No wallpapers found')

  const nextRaw = await redis.get('wallpaper:next-index')
  const nextIndex = nextRaw === null ? 0 : Number(nextRaw)
  const safeIndex = Number.isFinite(nextIndex) ? nextIndex : 0
  const index = safeIndex % wallpapers.length
  const fileName = wallpapers[index]

  await redis.set('wallpaper:next-index', String(index + 1))

  const url = `https://raw.githubusercontent.com/kevmio29-arch/tmdb-france-wallpapers/main/wallpapers/${encodeURIComponent(fileName)}`
  const title = fileName
    .replace(/\.jpg$/i, '')
    .replace(/^(film|serie)_\d+_\d+_/, '')
    .replace(/_/g, ' ')

  const uploaded = await media.upload({url, type: 'image'})
  const richtext = new RichTextBuilder().paragraph((p) => {
    p.image({mediaUrl: uploaded.mediaUrl})
  })

  await reddit.submitPost({
    subredditName: context.subredditName,
    title: `${title} | TMDB France`,
    richtext,
  })

  return {title, url}
}

async function routeAppInstall(): Promise<TriggerResponse> {
  await reddit.submitCustomPost({title: context.appSlug})
  return {}
}

async function readJson<T>(reqMsg: IncomingMessage): Promise<T> {
  const chunks: Uint8Array[] = []
  reqMsg.on('data', chunk => chunks.push(chunk))
  await once(reqMsg, 'end')
  return JSON.parse(`${Buffer.concat(chunks)}`)
}

function writeJson<T extends PartialJsonValue>(
  status: number,
  json: Readonly<T>,
  rsp: ServerResponse,
): void {
  const body = JSON.stringify(json)
  const len = Buffer.byteLength(body)
  rsp.writeHead(status, {
    'Content-Length': len,
    'Content-Type': 'application/json',
  })
  rsp.end(body)
}
