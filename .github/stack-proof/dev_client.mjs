// Synthetic-development commissioning only. Run inside the ORIGINAL compiled
// Conductor container via secret-env.mjs. This client never signs or creates
// operation records; all write/recovery records belong to the real application.
// Usage: node /proof/dev_client.mjs PHASE http://198.51.100.10:8082 [LOCAL_ID]
// PHASE: seed | known | unknown | terminal-lost-reply | race | status | recover | recover-refused
// Root must separately set Bridge NODE_ENV=test + test keyring and the explicit
// external.py --synthetic-development-mutations capability in isolated CI.
// terminal-lost-reply requires ROOT's transport relay to discard one ACTUAL
// Server mutation reply after dispatch. recover requires actual trusted terminal
// proof, or actual offline unknown resolution performed by the stopped writer's
// reviewed operator helper. This client does neither of those operator steps.
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {MongoClient, ObjectId} from '/usr/src/conductor/server/node_modules/mongodb/lib/index.js';
import bcrypt from '/usr/src/conductor/server/node_modules/bcryptjs/index.js';

const [phase, controlOrigin, selectedLocalID] = process.argv.slice(2);
const phases = new Set(['seed', 'known', 'unknown', 'terminal-lost-reply', 'race', 'status', 'recover', 'recover-refused']);
const requireFact = (condition, code) => { if (!condition) throw Error(code); };
const digest = value => createHash('sha256').update(value).digest('hex');
const checkpoint = (stage, details = {}) => console.log(JSON.stringify({phase, checkpoint: stage, passed: true, ...details}));
let client;

async function run() {
  requireFact(phases.has(phase), 'invalid_phase');
  requireFact(controlOrigin === 'http://198.51.100.10:8082', 'reserved_external_control_required');
  requireFact(/^v22\./.test(process.version), 'actual_node22_required');
  // Production cookie/session settings remain exercised. Only the separate
  // Bridge test runtime enables the already-delivered synthetic signed path.
  requireFact(process.env.NODE_ENV === 'production', 'conductor_production_session_profile_required');
  const info = fs.lstatSync('/fixture/app.json');
  requireFact(info.isFile() && !info.isSymbolicLink() && !(info.mode & 0o077) && info.size < 16384,
    'private_synthetic_fixture_required');
  const config = JSON.parse(fs.readFileSync('/fixture/app.json', 'utf8'));
  requireFact(config.pageURL === 'https://dev.libretexts.org/Sandboxes/johnnyphung/Stack/Synthetic', 'synthetic_page_required');
  requireFact(typeof config.projectID === 'string' && /^[\w-]{1,100}$/.test(config.projectID)
    && /^[a-f0-9]{24}$/i.test(config.sectionID) && typeof config.password === 'string', 'fixture_shape_required');
  const processes = fs.readdirSync('/proc').filter(p => /^\d+$/.test(p)).flatMap(p => {
    try { return [fs.readFileSync('/proc/' + p + '/cmdline', 'utf8').replaceAll('\0', ' ').trim()]; }
    catch { return []; }
  });
  requireFact(processes.includes('node dist/server.js'), 'actual_compiled_entrypoint_required');
  client = new MongoClient(process.env.MONGOOSEURI, {serverSelectionTimeoutMS: 10000});
  await client.connect();
  const db = client.db(), projectFilter = {projectID: config.projectID};
  // Deterministic synthetic administrator identity, distinct from the editor.
  // Only ordinary users/org/project fixtures are seeded; no intents/ledger.
  const adminID = config.admin || digest(config.projectID).slice(0, 32);
  const identities = {editor: config.editor, auditor: config.auditor, outsider: config.outsider, admin: adminID};
  if (phase === 'seed') {
    for (const [name, uuid] of Object.entries(identities)) {
      requireFact(typeof uuid === 'string' && uuid.length > 0 && uuid.length <= 128, 'synthetic_user_identity_required');
      const email = name + '@candidate.example.invalid';
      const existing = await db.collection('users').findOne({$or: [{uuid}, {email}]});
      if (existing) {
        requireFact(existing.uuid === uuid && existing.email === email && existing.centralID === 'synthetic-' + name,
          'refuse_existing_nonsynthetic_user');
        if (name === 'admin') requireFact(existing.roles?.some(r => r.org === 'libretexts' && r.role === 'support'), 'existing_admin_role_required');
      } else await db.collection('users').insertOne({uuid, centralID: 'synthetic-' + name, email,
        firstName: 'Synthetic', lastName: name, authType: 'traditional', password: await bcrypt.hash(config.password, 4),
        roles: [{org: 'libretexts', role: name === 'admin' ? 'support' : 'user'}], verifiedInstructor: true, uxAcknowledgments: {}});
    }
    const organization = await db.collection('organizations').findOne({orgID: 'libretexts'});
    if (!organization) await db.collection('organizations').insertOne({orgID: 'libretexts', active: true, name: 'Synthetic candidate',
      subdomain: 'candidate', domain: 'https://conductor.invalid', commonsModules: {projects: {enabled: true, order: 1}}});
    else requireFact(organization.domain === 'https://conductor.invalid', 'refuse_existing_nonsynthetic_organization');
    const existing = await db.collection('projects').findOne(projectFilter);
    if (!existing) await db.collection('projects').insertOne({...projectFilter, orgID: 'libretexts', title: 'Full owned stack synthetic',
      status: 'open', classification: 'construction', projectURL: '', libreLibrary: '', libreCoverID: '', contentArea: 'Synthetic',
      visibility: 'private', members: [config.editor], leads: [], liaisons: [], auditors: [config.auditor], tags: [],
      a11yReview: [{_id: new ObjectId(config.sectionID), sectionTitle: 'Synthetic reader', sectionURL: config.pageURL, pageID: '42'}]});
    else requireFact(existing.orgID === 'libretexts' && existing.members?.includes(config.editor)
      && existing.a11yReview?.some(s => String(s._id) === config.sectionID && s.sectionURL === config.pageURL && s.pageID === '42'),
    'refuse_existing_nonsynthetic_project');
    checkpoint('synthetic_users_org_project_only');
    return;
  }

  const origin = 'http://127.0.0.1:5000', cookies = {};
  async function boundedJSON(response) {
    const reader = response.body.getReader(); let size = 0; const chunks = [];
    for (;;) {
      const {value, done} = await reader.read(); if (done) break;
      size += value.length;
      if (size > 6000000) { await reader.cancel(); throw Error('bounded_response_exceeded'); }
      chunks.push(value);
    }
    try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { throw Error('json_response_required'); }
  }
  for (const name of Object.keys(identities)) {
    const response = await fetch(origin + '/api/v1/auth/fallback-auth', {method: 'POST', redirect: 'manual',
      headers: {'Content-Type': 'application/json', Origin: 'https://conductor.invalid'},
      body: JSON.stringify({email: name + '@candidate.example.invalid', password: config.password}), signal: AbortSignal.timeout(30000)});
    requireFact(response.status === 302, 'actual_fallback_authentication_failed');
    const set = response.headers.getSetCookie();
    requireFact(set.some(c => /Secure/i.test(c)) && set.some(c => /Domain=conductor.invalid/i.test(c)), 'production_session_cookie_required');
    cookies[name] = set.map(c => c.split(';')[0]).join('; ');
  }
  async function request(path, body, user = 'editor') {
    const response = await fetch(origin + '/api/v1' + path, {method: body === undefined ? 'GET' : 'POST', redirect: 'error',
      headers: {'Content-Type': 'application/json', Origin: 'https://conductor.invalid', 'X-Requested-With': 'XMLHttpRequest',
        ...(user ? {Cookie: cookies[user]} : {})}, ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      signal: AbortSignal.timeout(650000)});
    return {status: response.status, data: await boundedJSON(response)};
  }
  async function control(path = '/control/status', body) {
    const response = await fetch(controlOrigin + path, {method: body === undefined ? 'GET' : 'POST', redirect: 'error',
      headers: {'Content-Type': 'application/json', 'X-Fixture-Control': 'synthetic-control-only'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}), signal: AbortSignal.timeout(10000)});
    requireFact(response.status === 200, 'synthetic_external_control_failed');
    const state = await boundedJSON(response);
    requireFact(Number.isSafeInteger(state.writes) && Number.isSafeInteger(state.revision), 'explicit_synthetic_external_capability_required');
    return state;
  }
  const base = `/project/${config.projectID}/accessibility/workqueue`, page = base + '/page/' + config.sectionID;
  const input = {projectID: config.projectID, sectionID: config.sectionID, fixMode: 'deterministic'};
  const project = () => db.collection('projects').findOne(projectFilter);
  const section = p => p.a11yReview.find(s => String(s._id) === config.sectionID);
  const records = () => db.collection('remedyoperationrecords').find(projectFilter).sort({_id: 1}).toArray();
  let originalRecords = await records();
  const immutable = async () => {
    const current = await records(), byID = new Map(current.map(r => [String(r._id), r]));
    requireFact(originalRecords.every(r => JSON.stringify(byID.get(String(r._id))) === JSON.stringify(r)), 'original_journal_changed');
    originalRecords = current;
    return current;
  };
  const conformance = async () => {
    const result = await request(base + '/conformance');
    requireFact(result.status === 200 && result.data.report.verifiedCriteria === 0, 'human_verification_must_remain_zero');
  };
  requireFact((await request('/project/accessibility/remedy/health?projectID=' + config.projectID, undefined, '')).status === 401, 'unauthenticated_request_not_denied');
  requireFact((await request(page + '/scan', input, 'outsider')).status === 403, 'outsider_request_not_denied');
  requireFact((await request(page + '/scan', input, 'auditor')).status === 403, 'auditor_request_not_denied');
  checkpoint('actual_compiled_node22_fallback_sessions_project_authorization');
  const initialExternal = await control();

  async function prepare() {
    const health = await request('/project/accessibility/remedy/health?projectID=' + config.projectID);
    requireFact(health.status === 200 && health.data.profile?.name === 'full-write' && health.data.capabilities?.mutate === true,
      'synthetic_test_bridge_write_readiness_required');
    const scan = await request(page + '/rendered-scan', input);
    requireFact(scan.status === 200 && scan.data.wcag_review?.rendered?.state === 'complete', 'actual_rendered_scan_required');
    const findingIDs = scan.data.findings.filter(f => f.fixable && f.ruleId === 'table-header').map(f => f.id);
    requireFact(findingIDs.length === 1, 'actual_explicit_table_header_finding_required');
    const selected = {...input, findingIDs};
    const preview = await request(page + '/preview', selected);
    requireFact(preview.status === 200 && preview.data.localReviewID && preview.data.review_binding?.action === 'cxone.apply',
      'authoritative_stored_preview_required');
    const current = await control();
    requireFact(current.source_sha256 === preview.data.review_binding.before_sha256
      && digest(preview.data.after_html) === preview.data.review_binding.after_sha256, 'reviewed_exact_source_bytes_required');
    requireFact(preview.data.review_binding.before_sha256 !== preview.data.review_binding.after_sha256
      && preview.data.applied_finding_ids?.includes(findingIDs[0]), 'actual_deterministic_changed_preview_required');
    checkpoint('actual_rendered_scan_selected_findings_stored_preview', {findingCount: findingIDs.length});
    return {selected, preview: preview.data, confirmed: {...selected, confirmed: true, localReviewID: preview.data.localReviewID,
      previewHash: preview.data.preview_hash, previewToken: preview.data.preview_token}};
  }
  async function knownWrite(result, action, before, afterHash) {
    const success = result.status === 200 && result.data?.outcome === 'known_success' && result.data?.writeOutcome === 'written'
      && result.data?.[action === 'apply' ? 'applied' : 'restored'] === true && typeof result.data?.audit_recorded === 'boolean';
    if (!success) {
      // Bounded public categories only. Never print product bodies, messages,
      // headers, signatures, cookies, bindings or private database events.
      const category = (value, allowed) => allowed.includes(value) ? value : value === undefined ? 'absent' : 'other';
      const reasons = new Map([
        ['Generate and explicitly confirm the current stored preview in this session before writing.', 'stored_preview_refused'],
        ['The preview or project changed. Refresh before continuing.', 'claim_refused'],
        ['Reviewed writes are unavailable. The deployment operator must configure a valid signing key and validity window.', 'signer_unavailable'],
        ['Write outcome is unknown. Keep the page blocked and read operation evidence; do not retry automatically.', 'unknown_outcome'],
      ]);
      let local = {diagnosticReadFailed: true};
      try {
        const current = section(await project()), events = await records();
        local = {intentCount: events.filter(event => event.kind === 'intent').length,
          responseCount: events.filter(event => event.kind === 'response').length,
          pending: current?.remedyWritePending === true, storedPreviewPresent: Boolean(current?.remedyReviewedPreview),
          storedPreviewUsed: current?.remedyReviewedPreview?.used === true};
      } catch { /* Preserve the original failing assertion even if reads fail. */ }
      console.error(JSON.stringify({phase, passed: false, code: 'known_write_response_diagnostic', status: result.status,
        outcome: category(result.data?.outcome, ['not_attempted', 'pending', 'known_success', 'unknown_write']),
        operationReason: category(result.data?.reason, ['no_change', 'pre_dispatch_failure', 'stale_preview', 'target_mismatch', 'write_outcome_unknown']),
        writeOutcome: category(result.data?.writeOutcome, ['not_started', 'written', 'not_written', 'uncertain']),
        reason: reasons.get(result.data?.errMsg) || 'other',
        responseSHA256: digest(JSON.stringify(result.data)), ...local}));
    }
    requireFact(success, 'real_known_success_required');
    requireFact(result.data.scan && !result.data.scanError && !result.data.evidenceError, 'genuine_postwrite_rescan_required');
    const current = await control();
    requireFact(current.writes === before.writes + 1 && current.source_sha256 === afterHash, 'exactly_one_reviewed_external_write_required');
    const stored = section(await project());
    requireFact(stored.remedyWritePending === false && !stored.remedyPendingOperation
      && stored.wcagReview.sourceHash === afterHash.slice(0, stored.wcagReview.sourceHash.length), 'fresh_persisted_scan_required');
    const journal = await immutable();
    const intent = journal.find(r => r.kind === 'intent' && r.localID === result.data.localOperationID)?.event;
    requireFact(intent?.actor === config.editor && intent.action === action && intent.binding.after_sha256 === afterHash,
      'actual_actor_bound_intent_required');
    const response = journal.find(r => r.kind === 'response' && r.localID === result.data.localOperationID)?.event;
    requireFact(response?.operation?.outcome === 'known_success' && response.operation.audit_recorded === result.data.audit_recorded,
      'immutable_actual_outcome_required');
    const history = await request(page + '/operations/' + result.data.localOperationID + '/history');
    requireFact(history.status === 200 && history.data.records.some(r => r.kind === 'intent')
      && history.data.records.some(r => r.kind === 'response'), 'actual_authenticated_history_required');
    checkpoint('actual_signed_' + action + '_rescan_history', {localOperationID: result.data.localOperationID,
      operationID: result.data.operation_id, auditRecorded: result.data.audit_recorded});
    return result.data.localOperationID;
  }
  async function observe(localID) {
    const beforeProject = await project(), beforeRecords = await records(), beforeExternal = await control();
    const result = await request(page + '/operations/' + localID, undefined, 'admin');
    requireFact(result.status === 200 && result.data.readOnly === true, 'actual_readonly_status_required');
    requireFact(JSON.stringify(await project()) === JSON.stringify(beforeProject) && JSON.stringify(await records()) === JSON.stringify(beforeRecords),
      'lookup_changed_local_state');
    requireFact((await control()).writes === beforeExternal.writes, 'lookup_dispatched_external_write');
    return result.data;
  }

  if (['known', 'unknown', 'terminal-lost-reply', 'race'].includes(phase)) {
    const prepared = await prepare();
    const before = await control();
    if (phase === 'unknown') await control('/control/state', {lost_remote_response: true});
    if (phase === 'race') await control('/control/state', {hold_mutation: true});
    const dispatched = request(page + '/apply', prepared.confirmed);
    if (phase === 'race') {
      try {
        const deadline = Date.now() + 20000;
        while ((await control()).mutation_held === before.mutation_held) {
          requireFact(Date.now() < deadline, 'actual_dispatch_barrier_not_reached');
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        requireFact((await request(page + '/scan', input)).status === 409, 'pending_scan_not_blocked');
        requireFact((await request(page + '/apply', prepared.confirmed)).status === 409, 'concurrent_confirmation_not_blocked');
        checkpoint('actual_pending_claim_blocks_concurrent_actions');
      } finally { await control('/control/state', {hold_mutation: false}); }
    }
    const applied = await dispatched;
    if (phase === 'unknown' || phase === 'terminal-lost-reply') {
      requireFact(applied.status === 502 && applied.data.writeOutcome === 'uncertain' && applied.data.localOperationID, 'actual_uncertain_local_response_required');
      const pending = section(await project());
      requireFact(pending.remedyWritePending === true && pending.remedyPendingOperation === applied.data.localOperationID, 'actual_pending_claim_required');
      const status = await observe(applied.data.localOperationID);
      requireFact((await control()).writes === before.writes + 1, 'unknown_must_commit_exactly_one_fake_external_write');
      requireFact(status.pending === true && (phase === 'unknown' ? status.operation.outcome === 'unknown_write'
        && status.operation.requires_reconciliation === true : status.operation.outcome === 'known_success'), 'actual_expected_remote_outcome_required');
      requireFact((await request(page + '/scan', input)).status === 409, 'unknown_scan_not_blocked');
      const journal = await immutable();
      requireFact(journal.some(r => r.localID === applied.data.localOperationID && r.kind === 'intent' && r.event.actor === config.editor), 'original_actor_intent_required');
      checkpoint('actual_pending_unknown_or_lost_terminal_reply', {localOperationID: applied.data.localOperationID,
        operationID: status.operation.operation_id, outcome: status.operation.outcome, evidenceVersion: status.evidenceVersion,
        auditRecorded: status.operation.audit_recorded,
        requiresReconciliation: status.operation.requires_reconciliation, externalWrites: (await control()).writes - before.writes});
    } else {
      await knownWrite(applied, 'apply', before, prepared.preview.review_binding.after_sha256);
      const writes = (await control()).writes;
      const replay = await request(page + '/apply', prepared.confirmed);
      requireFact(replay.status === 409 && (await control()).writes === writes, 'duplicate_confirmation_must_not_write');
      checkpoint('duplicate_local_confirmation_rejected_without_external_write');
      const snapshots = await request(page + '/snapshots', input);
      requireFact(snapshots.status === 200 && Array.isArray(snapshots.data.snapshots), 'actual_snapshot_list_required');
      const snapshot = snapshots.data.snapshots.find(s => s.hash === prepared.preview.review_binding.before_sha256.slice(0, 16));
      requireFact(snapshot && typeof snapshot.timestamp === 'string', 'actual_preapply_snapshot_required');
      const restoreInput = {...input, fixMode: 'restore', snapshotTimestamp: snapshot.timestamp};
      const preview = await request(page + '/restore-preview', restoreInput);
      requireFact(preview.status === 200 && preview.data.review_binding?.action === 'cxone.restore'
        && preview.data.review_binding.after_sha256 === prepared.preview.review_binding.before_sha256, 'actual_authoritative_restore_preview_required');
      const restoreBefore = await control();
      const restored = await request(page + '/restore', {...restoreInput, confirmed: true, localReviewID: preview.data.localReviewID,
        previewHash: preview.data.preview_hash, previewToken: preview.data.preview_token});
      await knownWrite(restored, 'restore', restoreBefore, preview.data.review_binding.after_sha256);
      requireFact((await control()).source_sha256 === initialExternal.source_sha256, 'restore_original_exact_bytes_required');
    }
  } else {
    const stored = section(await project()), localID = selectedLocalID || stored.remedyPendingOperation;
    requireFact(typeof localID === 'string' && /^[a-f0-9-]{36}$/i.test(localID), 'stored_local_operation_required');
    const observed = await observe(localID);
    if (phase === 'status') {
      checkpoint('readonly_historical_status_preserves_original_records', {localOperationID: localID,
        operationID: observed.operation.operation_id, outcome: observed.operation.outcome,
        reconciliation: observed.operation.reconciliation, auditRecorded: observed.operation.audit_recorded,
        pending: observed.pending, evidenceVersion: observed.evidenceVersion});
    } else {
      requireFact(observed.pending === true, 'explicit_recovery_requires_pending_claim');
      const historyBefore = await records();
      const projectBefore = await project();
      const result = await request(page + '/operations/' + localID + '/resolve', {expectedVersion: observed.evidenceVersion,
        confirmed: true, reason: 'Synthetic operator explicitly requests fresh canonical evidence after trusted remote settlement.'}, 'admin');
      if (phase === 'recover-refused') {
        requireFact(result.status >= 400 && result.status < 600, 'unsafe_recovery_must_be_refused');
        requireFact(JSON.stringify(await project()) === JSON.stringify(projectBefore)
          && JSON.stringify(await records()) === JSON.stringify(historyBefore), 'refused_recovery_changed_claim_or_journal');
        requireFact((await control()).writes === initialExternal.writes, 'refused_recovery_dispatched_mutation');
        checkpoint('untrusted_or_unresolved_recovery_refused_claim_held', {localOperationID: localID,
          status: result.status, originalOutcome: observed.operation.outcome, pending: true});
        await conformance();
        return;
      }
      requireFact(result.status === 200 && result.data.resolved === true, 'actual_explicit_recovery_failed');
      const after = await project(), current = section(after);
      requireFact(current.remedyWritePending === false && !current.remedyPendingOperation
        && current.remedyEvidenceVersion === observed.evidenceVersion + 1 && current.wcagReview?.sourceHash,
        'actual_fresh_scan_cas_release_required');
      requireFact((await control()).writes === initialExternal.writes, 'recovery_must_never_dispatch_mutation');
      const journal = await immutable(), byID = new Map(journal.map(r => [String(r._id), r]));
      requireFact(historyBefore.every(r => JSON.stringify(byID.get(String(r._id))) === JSON.stringify(r)), 'recovery_rewrote_original_history');
      const resolution = journal.find(r => r.kind === 'resolution' && r.localID === localID && r.event.resolutionID === result.data.resolutionID)?.event;
      requireFact(resolution?.actor === adminID && resolution.originalActor === config.editor
        && JSON.stringify(resolution.operation) === JSON.stringify(observed.operation)
        && after.remedyResolutionCommits.some(r => r.id === result.data.resolutionID), 'actual_preparation_and_commit_required');
      const duplicate = await request(page + '/operations/' + localID + '/resolve', {expectedVersion: observed.evidenceVersion,
        confirmed: true, reason: 'Synthetic duplicate explicit resolution must be refused without a remote write.'}, 'admin');
      requireFact(duplicate.status === 409, 'duplicate_resolution_not_rejected');
      checkpoint('actual_explicit_recovery_fresh_scan_immutable_history', {localOperationID: localID,
        resolutionID: result.data.resolutionID, originalOutcome: observed.operation.outcome,
        auditRecorded: observed.operation.audit_recorded, recoveryKind: resolution.recoveryKind,
        terminalProofPresent: Boolean(resolution.terminalProof), evidenceVersion: current.remedyEvidenceVersion});
    }
  }
  await immutable(); await conformance();
  checkpoint('phase_complete', {verifiedCriteria: 0, externalWrites: (await control()).writes - initialExternal.writes,
    deploymentReady: false, productionWritesEnabled: false});
}

try { await run(); }
catch (error) {
  // Do not emit assertions, credential bytes, cookies, bindings, HTML or private
  // paths, even when an application/provider returns an unexpected error.
  const code = /^[a-z][a-z0-9_]{1,100}$/.test(error?.message || '') ? error.message : 'synthetic_phase_failed';
  console.error(JSON.stringify({phase: phases.has(phase) ? phase : 'invalid', passed: false, code}));
  process.exitCode = 1;
} finally { if (client) await client.close(); }
