import { useState, type ReactElement } from 'react'
import { replayErrorView, type ReplayActionId } from './replayErrors'

type Step =
  | 'choose'
  | 'validating'
  | 'identifying'
  | 'matching'
  | 'checking_league'
  | 'linked'
  | 'failed'
  | 'participants'
  | 'building'
  | 'switching'

type ParticipantRow = {
  participant_id: number
  champion_name: string
  team_id: number
  individual_position?: string | null
  riot_id_game_name?: string | null
  riot_id_tagline?: string | null
}

type Props = {
  open: boolean
  matchId: string
  onClose: () => void
  onLinked: (sourceId: string, matchId: string) => void
  onOpenReview: (reviewId: string) => void
  onAction: (action: ReplayActionId) => void
}

export function ImportReplayWizard(props: Props): ReactElement | null {
  const [step, setStep] = useState<Step>('choose')
  const [errorLabel, setErrorLabel] = useState<string | null>(null)
  const [infoLabel, setInfoLabel] = useState<string | null>(null)
  const [actionId, setActionId] = useState<ReplayActionId | null>(null)
  const [actionLabel, setActionLabel] = useState<string | null>(null)
  const [patch, setPatch] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingPath, setPendingPath] = useState<string | null>(null)
  const [replayMatchId, setReplayMatchId] = useState<string | null>(null)
  const [participants, setParticipants] = useState<ParticipantRow[]>([])
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  if (!props.open) {
    return null
  }

  const reset = (): void => {
    setStep('choose')
    setErrorLabel(null)
    setInfoLabel(null)
    setActionId(null)
    setActionLabel(null)
    setPatch(null)
    setBusy(false)
    setPendingPath(null)
    setReplayMatchId(null)
    setParticipants([])
    setActiveJobId(null)
  }

  const failWith = (code: string, message?: string | null, suggested?: string | null): void => {
    const view = replayErrorView({ code, message, suggestedAction: suggested })
    setStep('failed')
    setInfoLabel(null)
    setErrorLabel(view.message)
    setActionId(view.actionId)
    setActionLabel(view.actionLabel)
    setBusy(false)
  }

  const finishLinked = async (
    sourceId: string,
    matchId: string,
    reviewId: string | null
  ): Promise<void> => {
    setStep('checking_league')
    await window.rift.checkGameplayEnvironment()
    setStep('linked')
    setInfoLabel(null)
    setBusy(false)
    props.onLinked(sourceId, matchId)
    if (reviewId !== null && reviewId.length > 0) {
      props.onOpenReview(reviewId)
    }
  }

  const bindAndFinish = async (
    path: string,
    matchId: string,
    reviewId: string | null
  ): Promise<void> => {
    setStep('matching')
    setInfoLabel(`Linking replay to ${matchId}…`)
    // Pass the replay's own match id so binding never uses an unrelated open review.
    const imported = await window.rift.importReplay(path, matchId)
    if (!imported.ok) {
      failWith(imported.code, imported.message, imported.suggested_action)
      return
    }
    setPatch(imported.identity?.declared_patch ?? imported.status.declared_patch)
    await finishLinked(imported.source_id, imported.match_id, reviewId)
  }

  const ensureReviewThenFinish = async (
    path: string,
    matchId: string,
    alreadySourceId: string | null
  ): Promise<void> => {
    const reviews = await window.rift.listReviews()
    if (reviews.ok) {
      const existing = reviews.reviews.find((row) => row.match_id === matchId)
      if (existing !== undefined) {
        if (alreadySourceId !== null) {
          await finishLinked(alreadySourceId, matchId, existing.id)
          return
        }
        await bindAndFinish(path, matchId, existing.id)
        return
      }
    }
    await loadParticipants(matchId, path)
  }

  const loadParticipants = async (matchId: string, path: string): Promise<void> => {
    setBusy(true)
    setErrorLabel(null)
    setPendingPath(path)
    setReplayMatchId(matchId)
    setStep('participants')
    setInfoLabel(`Loading players for ${matchId}…`)
    const listed = await window.rift.listMatchParticipants(matchId)
    if (!listed.ok) {
      failWith(listed.code, listed.message)
      return
    }
    setParticipants(listed.participants)
    setInfoLabel(`Choose your champion for ${matchId}.`)
    setBusy(false)
  }

  const openReplayMatchFlow = async (path: string, matchId: string): Promise<void> => {
    setBusy(true)
    setErrorLabel(null)
    setPendingPath(path)
    setReplayMatchId(matchId)
    setStep('switching')
    setInfoLabel(`Replay match is ${matchId}. Opening that review…`)
    await ensureReviewThenFinish(path, matchId, null)
  }

  const buildForParticipant = async (participantId: number): Promise<void> => {
    if (pendingPath === null || replayMatchId === null) {
      return
    }
    setBusy(true)
    setStep('building')
    setErrorLabel(null)
    setInfoLabel(`Building review for participant ${participantId}…`)
    const started = await window.rift.startAnalyzeJob({
      matchId: replayMatchId,
      participantId,
      rank: 'UNRANKED'
    })
    if (!started.ok) {
      failWith(started.code, started.message)
      return
    }
    setActiveJobId(started.job.job_id)
    let job = started.job
    while (job.status === 'QUEUED' || job.status === 'RUNNING') {
      setInfoLabel(
        `${job.current_stage ?? 'analyze'} ${job.progress_pct}% — ${job.progress_message}`
      )
      await new Promise((resolve) => setTimeout(resolve, 250))
      const polled = await window.rift.getAnalyzeJob(job.job_id)
      if (!polled.ok) {
        failWith(polled.code, polled.message)
        return
      }
      job = polled.job
    }
    if (job.status !== 'COMPLETED' || job.review_id === null) {
      failWith(job.error_code ?? 'JOB_FAILED', job.error_message)
      return
    }
    await bindAndFinish(pendingPath, replayMatchId, job.review_id)
  }

  const runImport = async (): Promise<void> => {
    setBusy(true)
    setErrorLabel(null)
    setInfoLabel(null)
    setStep('choose')
    const picked = await window.rift.pickRofl()
    if (!picked.ok) {
      failWith(picked.code, picked.message)
      return
    }
    if (picked.path === null) {
      setBusy(false)
      return
    }
    setPendingPath(picked.path)
    setStep('validating')
    // Never bind using the open review id — that caused fixture/wrong-match attachment.
    // Identify + bind against the ROFL's own match only.
    const imported = await window.rift.importReplay(picked.path, null)
    if (!imported.ok) {
      const hint =
        imported.match_id ??
        imported.identity?.match_id_hint ??
        (typeof imported.error?.details?.['replay_match_id'] === 'string'
          ? String(imported.error.details['replay_match_id'])
          : null)
      setReplayMatchId(hint)
      if (
        (imported.code === 'MATCH_NOT_INGESTED' || imported.code === 'MATCH_IDENTITY_MISMATCH') &&
        hint !== null
      ) {
        await openReplayMatchFlow(picked.path, hint)
        return
      }
      failWith(imported.code, imported.message, imported.suggested_action)
      return
    }
    setStep('identifying')
    setPatch(imported.identity?.declared_patch ?? imported.status.declared_patch)
    setReplayMatchId(imported.match_id)
    if (props.matchId.length === 0 || imported.match_id !== props.matchId) {
      setInfoLabel(`Replay belongs to ${imported.match_id}. Opening that review…`)
      await ensureReviewThenFinish(picked.path, imported.match_id, imported.source_id)
      return
    }
    setStep('matching')
    await finishLinked(imported.source_id, imported.match_id, null)
  }

  const handlePrimaryAction = (): void => {
    if (
      (actionId === 'open_replay_match' ||
        actionId === 'ingest_match' ||
        actionId === 'choose_participant') &&
      pendingPath !== null &&
      replayMatchId !== null
    ) {
      void openReplayMatchFlow(pendingPath, replayMatchId)
      return
    }
    if (actionId === 'sign_in_api_key') {
      props.onAction(actionId)
      return
    }
    props.onAction(actionId ?? 'choose_file')
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 p-4"
      data-testid="import-replay-wizard"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-700 bg-slate-950 p-4 text-slate-100">
        <h2 className="text-lg font-semibold">Import League Replay</h2>
        <p className="mt-1 text-xs text-slate-400">
          Linking does not launch League. Open Replay from the review screen when you are ready.
        </p>
        {step === 'participants' ? (
          <div className="mt-4" data-testid="import-participant-picker">
            <p className="text-sm text-slate-300">
              Choose whose review to build for {replayMatchId ?? 'this match'}.
            </p>
            <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto text-sm">
              {participants.map((row) => {
                const name =
                  row.riot_id_game_name && row.riot_id_tagline
                    ? `${row.riot_id_game_name}#${row.riot_id_tagline}`
                    : null
                return (
                  <li key={row.participant_id}>
                    <button
                      type="button"
                      disabled={busy}
                      data-testid={`import-participant-${row.participant_id}`}
                      className="flex w-full items-center justify-between rounded bg-slate-900 px-3 py-2 text-left hover:bg-slate-800 disabled:opacity-50"
                      onClick={() => {
                        void buildForParticipant(row.participant_id)
                      }}
                    >
                      <span>
                        {row.champion_name}
                        {row.individual_position ? ` · ${row.individual_position}` : ''}
                        {name ? ` · ${name}` : ''}
                      </span>
                      <span className="text-xs text-slate-500">P{row.participant_id}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : (
          <ol className="mt-4 space-y-1 text-sm" data-testid="import-wizard-step" data-step={step}>
            <StepRow done={past(step, 'choose')} current={step === 'choose'} label="Choose file" />
            <StepRow done={past(step, 'validating')} current={step === 'validating'} label="Validating replay" />
            <StepRow
              done={past(step, 'identifying')}
              current={step === 'identifying' || step === 'switching'}
              label="Identifying replay"
            />
            <StepRow
              done={past(step, 'matching')}
              current={step === 'matching' || step === 'building'}
              label={`Matching to ${replayMatchId ?? props.matchId}`}
            />
            <StepRow
              done={past(step, 'checking_league')}
              current={step === 'checking_league'}
              label="Checking League"
            />
            <StepRow done={step === 'linked'} current={step === 'linked'} label="Linked · ready to open" />
          </ol>
        )}
        {step === 'linked' ? (
          <p className="mt-3 text-sm text-emerald-200" data-testid="import-success">
            Replay linked{patch ? ` · patch ${patch}` : ''}. Ready to open.
          </p>
        ) : null}
        {infoLabel && step !== 'failed' ? (
          <p className="mt-3 text-sm text-sky-200" data-testid="import-info">
            {infoLabel}
          </p>
        ) : null}
        {step === 'failed' && errorLabel ? (
          <p className="mt-3 text-sm text-rose-300" data-testid="import-error">
            {errorLabel}
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {step !== 'linked' &&
          step !== 'participants' &&
          step !== 'building' &&
          step !== 'switching' ? (
            <button
              type="button"
              data-testid="import-choose-file"
              disabled={busy}
              className="rounded bg-sky-700 px-3 py-1.5 text-sm disabled:opacity-50"
              onClick={() => {
                void runImport()
              }}
            >
              {step === 'failed' ? 'Choose another file' : 'Choose .rofl'}
            </button>
          ) : null}
          {step === 'failed' && actionId && actionLabel && actionId !== 'choose_file' ? (
            <button
              type="button"
              data-testid="import-primary-action"
              className="rounded bg-slate-800 px-3 py-1.5 text-sm"
              onClick={handlePrimaryAction}
            >
              {actionLabel}
            </button>
          ) : null}
          <button
            type="button"
            className="rounded bg-slate-800 px-3 py-1.5 text-sm"
            onClick={() => {
              if (activeJobId !== null) {
                void window.rift.cancelAnalyzeJob(activeJobId)
              }
              reset()
              props.onClose()
            }}
          >
            {step === 'linked' ? 'Done' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  )
}

function past(step: Step, target: Step): boolean {
  const order: Step[] = [
    'choose',
    'validating',
    'identifying',
    'matching',
    'checking_league',
    'linked'
  ]
  if (step === 'failed' || step === 'participants' || step === 'building' || step === 'switching') {
    return false
  }
  return order.indexOf(step) > order.indexOf(target)
}

function StepRow(props: { done: boolean; current: boolean; label: string }): ReactElement {
  return (
    <li className={props.current ? 'text-sky-200' : props.done ? 'text-slate-300' : 'text-slate-500'}>
      {props.done ? '✓ ' : props.current ? '→ ' : '· '}
      {props.label}
    </li>
  )
}
