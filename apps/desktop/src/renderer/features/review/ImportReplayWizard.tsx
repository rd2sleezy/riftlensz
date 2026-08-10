import { useState, type ReactElement } from 'react'
import { replayErrorView, type ReplayActionId } from './replayErrors'

type Step = 'choose' | 'validating' | 'identifying' | 'matching' | 'checking_league' | 'linked' | 'failed'

type Props = {
  open: boolean
  matchId: string
  onClose: () => void
  onLinked: (sourceId: string) => void
  onAction: (action: ReplayActionId) => void
}

export function ImportReplayWizard(props: Props): ReactElement | null {
  const [step, setStep] = useState<Step>('choose')
  const [errorLabel, setErrorLabel] = useState<string | null>(null)
  const [actionId, setActionId] = useState<ReplayActionId | null>(null)
  const [actionLabel, setActionLabel] = useState<string | null>(null)
  const [patch, setPatch] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!props.open) {
    return null
  }

  const reset = (): void => {
    setStep('choose')
    setErrorLabel(null)
    setActionId(null)
    setActionLabel(null)
    setPatch(null)
    setBusy(false)
  }

  const runImport = async (): Promise<void> => {
    setBusy(true)
    setErrorLabel(null)
    setStep('choose')
    const picked = await window.rift.pickRofl()
    if (!picked.ok) {
      const view = replayErrorView({ code: picked.code, message: picked.message })
      setStep('failed')
      setErrorLabel(view.message)
      setActionId(view.actionId)
      setActionLabel(view.actionLabel)
      setBusy(false)
      return
    }
    if (picked.path === null) {
      setBusy(false)
      return
    }
    setStep('validating')
    const imported = await window.rift.importReplay(picked.path, props.matchId)
    if (!imported.ok) {
      const view = replayErrorView({
        code: imported.code,
        message: imported.message,
        suggestedAction: imported.suggested_action
      })
      setStep('failed')
      setErrorLabel(view.message)
      setActionId(view.actionId)
      setActionLabel(view.actionLabel)
      setBusy(false)
      return
    }
    setStep('identifying')
    setPatch(imported.identity?.declared_patch ?? imported.status.declared_patch)
    setStep('matching')
    setStep('checking_league')
    await window.rift.checkGameplayEnvironment()
    setStep('linked')
    setBusy(false)
    props.onLinked(imported.source_id)
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
        <ol className="mt-4 space-y-1 text-sm" data-testid="import-wizard-step" data-step={step}>
          <StepRow done={past(step, 'choose')} current={step === 'choose'} label="Choose file" />
          <StepRow done={past(step, 'validating')} current={step === 'validating'} label="Validating replay" />
          <StepRow
            done={past(step, 'identifying')}
            current={step === 'identifying'}
            label="Identifying replay"
          />
          <StepRow
            done={past(step, 'matching')}
            current={step === 'matching'}
            label={`Matching to ${props.matchId}`}
          />
          <StepRow
            done={past(step, 'checking_league')}
            current={step === 'checking_league'}
            label="Checking League"
          />
          <StepRow done={step === 'linked'} current={step === 'linked'} label="Linked · ready to open" />
        </ol>
        {step === 'linked' ? (
          <p className="mt-3 text-sm text-emerald-200" data-testid="import-success">
            Replay linked{patch ? ` · patch ${patch}` : ''}. Ready to open.
          </p>
        ) : null}
        {step === 'failed' && errorLabel ? (
          <p className="mt-3 text-sm text-rose-300" data-testid="import-error">
            {errorLabel}
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {step !== 'linked' ? (
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
              className="rounded bg-slate-800 px-3 py-1.5 text-sm"
              onClick={() => props.onAction(actionId)}
            >
              {actionLabel}
            </button>
          ) : null}
          <button
            type="button"
            className="rounded bg-slate-800 px-3 py-1.5 text-sm"
            onClick={() => {
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
  if (step === 'failed') {
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
