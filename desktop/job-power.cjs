const LONG_ACTIONS = new Set(['tutorial', 'ask', 'generate_quiz', 'submit_quiz', 'related', 'search', 'build_index', 'sync_mem0', 'test_model',
  'import_video', 'import_vault', 'start_video_job', 'import_local_media', 'retry_media_job']);
const ACTIVE = new Set(['queued', 'running']);
class JobPowerGuard {
  constructor(blocker) {
    this.blocker = blocker;
    this.inflight = 0;
    this.mediaActive = false;
    this.token = null;
    this.polling = false;
    this.epoch = 0;
    this.observation = 0;
    this.disposed = false;
  }
  sync() {
    const active = !this.disposed && (this.inflight > 0 || this.mediaActive);
    if (active && this.token === null) this.token = this.blocker.start('prevent-app-suspension');
    if (!active && this.token !== null) { this.blocker.stop(this.token); this.token = null; }
  }
  observe(action, result) {
    if (this.disposed) return;
    const queue = action === 'bootstrap' ? result?.media_jobs : action === 'media_jobs' && Array.isArray(result) ? result : null;
    let activity;
    if (action === 'media_activity' && typeof result?.active === 'boolean') activity = result.active;
    else if (action === 'bootstrap' && typeof result?.media_active === 'boolean') activity = result.media_active;
    else if (Array.isArray(queue) && queue.some(job => ACTIVE.has(job?.status))) activity = true;
    else if (['start_video_job','import_local_media','retry_media_job','cancel_media_job','media_jobs'].includes(action) && ACTIVE.has(result?.status)) activity = true;
    if (typeof activity === 'boolean') { this.mediaActive = activity; this.observation++; }
    // Neither individual terminal results nor bounded UI history prove the queue is idle.
    this.sync();
  }
  async run(action, operation) {
    const epoch = this.epoch;
    const tracked = !this.disposed && LONG_ACTIONS.has(action);
    if (tracked) { this.inflight++; this.sync(); }
    try {
      const result = await operation();
      if (epoch === this.epoch) this.observe(action, result);
      return result;
    } finally {
      if (tracked && epoch === this.epoch) { this.inflight--; this.sync(); }
    }
  }
  async poll(query) {
    if (this.disposed || !this.mediaActive || this.polling) return;
    this.polling = true;
    const epoch = this.epoch;
    const observation = this.observation;
    try {
      const activity = await query();
      // rpc() may already have observed this response. Never replay it over a
      // newer admission or queue observation that completed in the meantime.
      if (epoch === this.epoch && observation === this.observation) this.observe('media_activity', activity);
    } catch { /* A failed observation is not evidence that media work ended. */ }
    finally { if (epoch === this.epoch) this.polling = false; }
  }
  reset() {
    this.epoch++;
    this.inflight = 0;
    this.mediaActive = false;
    this.polling = false;
    this.sync();
  }
  dispose() { this.disposed = true; this.reset(); }
}
module.exports = { JobPowerGuard };
