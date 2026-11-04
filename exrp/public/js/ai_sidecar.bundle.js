/**
 * EXRP Frappe Desk Embedded AI Sidecar (ADR-001 Rev 2.3)
 * Self-contained vanilla JavaScript class EXRPAISidecar.
 * Injects floating toggle launcher, slide-out drawer, interactive proposal cards,
 * 2-Axis Policy Gate inspection, DDL Plan Gate inspection, and 4-stage durable deployment.
 */

(function () {
  'use strict';

  // Ensure frappe namespace exists
  if (typeof window.frappe === 'undefined') {
    window.frappe = {};
  }
  if (typeof window.frappe.provide === 'function') {
    window.frappe.provide('exrp.sidecar');
  } else {
    window.exrp = window.exrp || {};
    window.exrp.sidecar = window.exrp.sidecar || {};
  }

  /**
   * Safe HTML string escaper
   */
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Main EXRPAISidecar Class
   */
  class EXRPAISidecar {
    constructor() {
      this.isOpen = false;
      this.activeDocType = null;
      this.customFieldCount = 0;
      this.isProcessing = false;
      this.isDeploying = false;
      this.messages = [];
      this.activeProposal = null;

      // DOM Elements
      this.launcherEl = null;
      this.drawerEl = null;
      this.backdropEl = null;
      this.chatStreamEl = null;
      this.inputEl = null;
      this.sendBtnEl = null;
      this.contextDocTypeEl = null;
      this.contextCountEl = null;
      this.headerDocTypeEl = null;

      this.init();
    }

    /**
     * Initializes DOM, Event Listeners, and Navigation watchers
     */
    init() {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => this.setup());
      } else {
        this.setup();
      }
    }

    setup() {
      if (document.getElementById('exrp-sidecar-drawer')) {
        return; // Already initialized in DOM
      }

      this.createDOM();
      this.bindEvents();
      this.updateContext();
      this.renderWelcomeMessage();

      // Hook into Frappe navigation and form events
      if (window.frappe && window.frappe.router && typeof window.frappe.router.on === 'function') {
        window.frappe.router.on('change', () => this.onRouteOrContextChange());
      }

      if (typeof window.$ !== 'undefined') {
        window.$(document).on('page-change', () => this.onRouteOrContextChange());
        window.$(document).on('form-refresh', () => this.onRouteOrContextChange());
      }

      // Context polling fallback for SPA switches
      setInterval(() => this.checkContextMismatch(), 1200);
    }

    /**
     * Builds and injects HTML structure for launcher, drawer, and backdrop
     */
    createDOM() {
      // 1. Floating Launcher Button
      this.launcherEl = document.createElement('button');
      this.launcherEl.id = 'exrp-sidecar-launcher';
      this.launcherEl.className = 'exrp-sidecar-launcher';
      this.launcherEl.setAttribute('type', 'button');
      this.launcherEl.setAttribute('aria-label', 'Open EXRP AI Sidecar');
      this.launcherEl.innerHTML = `
        <span class="exrp-launcher-icon">✨</span>
        <span class="exrp-launcher-text">EXRP AI</span>
        <span class="exrp-launcher-badge" id="exrp-launcher-badge"></span>
      `;
      document.body.appendChild(this.launcherEl);

      // 2. Backdrop Scrim
      this.backdropEl = document.createElement('div');
      this.backdropEl.className = 'exrp-sidecar-backdrop';
      this.backdropEl.id = 'exrp-sidecar-backdrop';
      document.body.appendChild(this.backdropEl);

      // 3. Slide-Out Drawer
      this.drawerEl = document.createElement('aside');
      this.drawerEl.className = 'exrp-sidecar-drawer';
      this.drawerEl.id = 'exrp-sidecar-drawer';
      this.drawerEl.setAttribute('aria-label', 'EXRP Configuration Copilot');

      this.drawerEl.innerHTML = `
        <!-- Drawer Header -->
        <div class="exrp-drawer-header">
          <div class="exrp-header-left">
            <span class="exrp-header-icon">✨</span>
            <div>
              <div class="exrp-header-title">EXRP Configuration Copilot</div>
              <div class="exrp-header-tagline">ADR-001 Rev 2.3 Safe Control Plane</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="exrp-doctype-badge" id="exrp-header-doctype-badge">Desk</span>
            <button class="exrp-btn-close" id="exrp-btn-close" title="Close Sidecar (Esc)">✕</button>
          </div>
        </div>

        <!-- DocType Context Bar -->
        <div class="exrp-context-bar">
          <div class="exrp-context-doctype">
            <span class="exrp-context-indicator" id="exrp-context-indicator"></span>
            <span id="exrp-context-doctype-text">No active form</span>
          </div>
          <div class="exrp-custom-field-count" id="exrp-context-count">
            0 custom fields
          </div>
        </div>

        <!-- Chat Stream -->
        <div class="exrp-chat-stream" id="exrp-chat-stream"></div>

        <!-- Prompt Input Bar -->
        <div class="exrp-input-bar">
          <div class="exrp-input-wrapper">
            <textarea
              class="exrp-prompt-input"
              id="exrp-prompt-input"
              rows="1"
              placeholder="Describe your configuration request (e.g., 'Add a priority status dropdown with Low, Medium, High')..."
            ></textarea>
            <button class="exrp-send-btn" id="exrp-send-btn" title="Send Request (Enter)" disabled>
              <svg class="exrp-send-icon" viewBox="0 0 24 24">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
          <div class="exrp-input-footer">
            <span>↵ Send · Shift+↵ Newline</span>
            <span>Zero-Downtime DDL Protection</span>
          </div>
        </div>
      `;

      document.body.appendChild(this.drawerEl);

      // Cache elements
      this.chatStreamEl = this.drawerEl.querySelector('#exrp-chat-stream');
      this.inputEl = this.drawerEl.querySelector('#exrp-prompt-input');
      this.sendBtnEl = this.drawerEl.querySelector('#exrp-send-btn');
      this.contextDocTypeEl = this.drawerEl.querySelector('#exrp-context-doctype-text');
      this.contextCountEl = this.drawerEl.querySelector('#exrp-context-count');
      this.headerDocTypeEl = this.drawerEl.querySelector('#exrp-header-doctype-badge');
    }

    /**
     * Binds UI click, keyboard, and resize event handlers
     */
    bindEvents() {
      // Toggle Drawer
      this.launcherEl.addEventListener('click', () => this.toggle());
      this.backdropEl.addEventListener('click', () => this.close());
      this.drawerEl.querySelector('#exrp-btn-close').addEventListener('click', () => this.close());

      // Keyboard Esc to close
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.isOpen) {
          this.close();
        }
      });

      // Textarea Auto-expand & Input Events
      this.inputEl.addEventListener('input', () => {
        this.inputEl.style.height = 'auto';
        this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 120) + 'px';
        this.sendBtnEl.disabled = !this.inputEl.value.trim() || this.isProcessing || this.isDeploying;
      });

      // Enter / Ctrl+Enter handler
      this.inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (!this.sendBtnEl.disabled) {
            this.handleSend();
          }
        }
      });

      // Send Button
      this.sendBtnEl.addEventListener('click', () => this.handleSend());

      // Quick prompt delegation
      this.chatStreamEl.addEventListener('click', (e) => {
        const chip = e.target.closest('.exrp-chip-btn');
        if (chip && chip.dataset.prompt) {
          this.inputEl.value = chip.dataset.prompt;
          this.inputEl.dispatchEvent(new Event('input'));
          this.handleSend();
        }

        // Copy DDL code button
        const copyBtn = e.target.closest('.exrp-ddl-copy-btn');
        if (copyBtn && copyBtn.dataset.sql) {
          navigator.clipboard.writeText(copyBtn.dataset.sql).then(() => {
            copyBtn.textContent = 'Copied!';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
          });
        }
      });
    }

    /**
     * Toggles sidecar drawer open/close
     */
    toggle() {
      if (this.isOpen) {
        this.close();
      } else {
        this.open();
      }
    }

    open() {
      this.isOpen = true;
      this.drawerEl.classList.add('exrp-open');
      this.backdropEl.classList.add('exrp-visible');
      this.updateContext();
      setTimeout(() => this.inputEl.focus(), 300);
      this.scrollToBottom();
    }

    close() {
      this.isOpen = false;
      this.drawerEl.classList.remove('exrp-open');
      this.backdropEl.classList.remove('exrp-visible');
    }

    /**
     * Resolves currently active DocType from cur_frm or frappe.router
     */
    getActiveDocType() {
      if (window.cur_frm && window.cur_frm.doctype) {
        return window.cur_frm.doctype;
      }
      if (window.frappe && typeof window.frappe.get_route === 'function') {
        const route = window.frappe.get_route();
        if (route && route[0] === 'Form' && route[1]) {
          return route[1];
        }
      }
      return null;
    }

    /**
     * Counts active custom fields on cur_frm
     */
    getCustomFieldsCount(doctype) {
      if (!doctype) return 0;
      if (window.cur_frm && window.cur_frm.doctype === doctype && window.cur_frm.meta && Array.isArray(window.cur_frm.meta.fields)) {
        return window.cur_frm.meta.fields.filter((f) => {
          return f.is_custom_field || (f.fieldname && f.fieldname.startsWith('custom_'));
        }).length;
      }
      return 0;
    }

    /**
     * Updates context bar, launcher badge, and header badge
     */
    updateContext() {
      const dt = this.getActiveDocType();
      this.activeDocType = dt;
      this.customFieldCount = this.getCustomFieldsCount(dt);

      const indicator = this.drawerEl.querySelector('#exrp-context-indicator');
      const launcherBadge = this.launcherEl.querySelector('#exrp-launcher-badge');

      if (dt) {
        this.contextDocTypeEl.textContent = dt;
        this.headerDocTypeEl.textContent = dt;
        this.contextCountEl.textContent = `${this.customFieldCount} custom field${this.customFieldCount === 1 ? '' : 's'}`;
        indicator.classList.remove('exrp-indicator-inactive');

        if (launcherBadge) {
          launcherBadge.textContent = dt;
          launcherBadge.style.display = 'inline-flex';
        }
        this.launcherEl.style.opacity = '1';
        this.launcherEl.title = `Configure ${dt} with EXRP AI`;
      } else {
        this.contextDocTypeEl.textContent = 'No active DocType form';
        this.headerDocTypeEl.textContent = 'Desk';
        this.contextCountEl.textContent = 'Form view required';
        indicator.classList.add('exrp-indicator-inactive');

        if (launcherBadge) {
          launcherBadge.style.display = 'none';
        }
        this.launcherEl.title = 'Open EXRP Configuration Copilot';
      }
    }

    onRouteOrContextChange() {
      const previousDocType = this.activeDocType;
      this.updateContext();
      if (previousDocType !== this.activeDocType && this.activeDocType) {
        this.appendSystemNotice(`Context switched to <strong>${escapeHtml(this.activeDocType)}</strong>.`);
      }
    }

    checkContextMismatch() {
      const dt = this.getActiveDocType();
      if (dt !== this.activeDocType) {
        this.onRouteOrContextChange();
      }
    }

    /**
     * Renders initial welcome message
     */
    renderWelcomeMessage() {
      const welcomeHtml = `
        <div class="exrp-msg-row exrp-msg-assistant">
          <div class="exrp-msg-avatar">✨</div>
          <div class="exrp-msg-body">
            <div class="exrp-msg-bubble">
              <p><strong>Welcome to EXRP Configuration Copilot!</strong></p>
              <p>I build enterprise customizations under ADR-001 Rev 2.3 rules: zero downtime, immutable Tier 0 invariant defense, and non-destructive schema reconciliations.</p>
              <p>Try one of these requests for the active form:</p>
              <div class="exrp-quick-prompts">
                <button type="button" class="exrp-chip-btn" data-prompt="Add a priority status dropdown with Low, Medium, High">⚡ Priority Dropdown</button>
                <button type="button" class="exrp-chip-btn" data-prompt="Add a cargo tracking number data field">📦 Tracking Number</button>
                <button type="button" class="exrp-chip-btn" data-prompt="Add an inspection notes text field">📝 Inspection Notes</button>
              </div>
            </div>
          </div>
        </div>
      `;
      this.chatStreamEl.innerHTML = welcomeHtml;
    }

    /**
     * Appends a user message bubble
     */
    appendUserMessage(text) {
      const row = document.createElement('div');
      row.className = 'exrp-msg-row exrp-msg-user';
      row.innerHTML = `<div class="exrp-msg-bubble">${escapeHtml(text)}</div>`;
      this.chatStreamEl.appendChild(row);
      this.scrollToBottom();
    }

    /**
     * Appends an assistant text message bubble
     */
    appendAssistantMessage(htmlContent) {
      const row = document.createElement('div');
      row.className = 'exrp-msg-row exrp-msg-assistant';
      row.innerHTML = `
        <div class="exrp-msg-avatar">✨</div>
        <div class="exrp-msg-body">
          <div class="exrp-msg-bubble">${htmlContent}</div>
        </div>
      `;
      this.chatStreamEl.appendChild(row);
      this.scrollToBottom();
    }

    /**
     * Appends a subtle system context notice
     */
    appendSystemNotice(noticeHtml) {
      const notice = document.createElement('div');
      notice.style.fontSize = '11.5px';
      notice.style.color = 'var(--exrp-text-muted)';
      notice.style.textAlign = 'center';
      notice.style.padding = '4px 0';
      notice.innerHTML = noticeHtml;
      this.chatStreamEl.appendChild(notice);
      this.scrollToBottom();
    }

    /**
     * Shows typing loading indicator
     */
    showLoading(text = 'Evaluating safety guardrails & generating DDL plan...') {
      this.hideLoading();
      const loadingRow = document.createElement('div');
      loadingRow.id = 'exrp-chat-loading';
      loadingRow.className = 'exrp-msg-row exrp-msg-assistant';
      loadingRow.innerHTML = `
        <div class="exrp-msg-avatar">✨</div>
        <div class="exrp-msg-body">
          <div class="exrp-loading-row">
            <div class="exrp-dots-loader">
              <span></span><span></span><span></span>
            </div>
            <span class="exrp-loading-text">${escapeHtml(text)}</span>
          </div>
        </div>
      `;
      this.chatStreamEl.appendChild(loadingRow);
      this.scrollToBottom();
    }

    hideLoading() {
      const el = document.getElementById('exrp-chat-loading');
      if (el) el.remove();
    }

    scrollToBottom() {
      setTimeout(() => {
        if (this.chatStreamEl) {
          this.chatStreamEl.scrollTop = this.chatStreamEl.scrollHeight;
        }
      }, 50);
    }

    /**
     * Handles submission of user prompt to Frappe backend
     */
    handleSend() {
      const prompt = this.inputEl.value.trim();
      if (!prompt || this.isProcessing || this.isDeploying) return;

      const doctype = this.activeDocType;
      if (!doctype) {
        if (window.frappe && typeof window.frappe.msgprint === 'function') {
          window.frappe.msgprint({
            title: __('Context Required'),
            message: __('Please open a DocType form (e.g. Sales Invoice, Delivery Note, Task) to propose customizations.'),
            indicator: 'orange',
          });
        }
        this.appendAssistantMessage('⚠️ <strong>No active DocType form found.</strong> Please navigate to any Frappe document or DocType form to configure fields.');
        return;
      }

      // Add user message to UI
      this.appendUserMessage(prompt);
      this.inputEl.value = '';
      this.inputEl.style.height = 'auto';
      this.sendBtnEl.disabled = true;
      this.isProcessing = true;
      this.showLoading(`Synthesizing proposal for ${doctype}...`);

      // Invoke Frappe backend RPC
      if (window.frappe && typeof window.frappe.call === 'function') {
        window.frappe.call({
          method: 'exrp.api.control_plane.propose_configuration_change',
          args: {
            doctype: doctype,
            user_prompt: prompt,
          },
          callback: (response) => {
            this.isProcessing = false;
            this.hideLoading();
            this.sendBtnEl.disabled = !this.inputEl.value.trim();

            if (response && response.message) {
              this.renderProposalCard(response.message, doctype);
            } else {
              this.appendAssistantMessage('⚠️ Received empty response from EXRP Control Plane.');
            }
          },
          error: (err) => {
            this.isProcessing = false;
            this.hideLoading();
            this.sendBtnEl.disabled = !this.inputEl.value.trim();
            const msg = err && err.message ? err.message : 'Error communicating with EXRP AI Planner.';
            this.appendAssistantMessage(`❌ <strong>Proposal Failed:</strong> ${escapeHtml(msg)}`);
          },
        });
      } else {
        // Fallback for standalone/demo testing
        setTimeout(() => {
          this.isProcessing = false;
          this.hideLoading();
          this.sendBtnEl.disabled = !this.inputEl.value.trim();
          this.renderMockProposal(prompt, doctype);
        }, 800);
      }
    }

    /**
     * Fallback mock proposal for offline / demonstration testing
     */
    renderMockProposal(prompt, doctype) {
      const mockResult = {
        status: 'PROPOSED',
        success: true,
        proposal: {
          intent: 'add_custom_fields',
          target_doctype: doctype,
          summary: `Add priority status dropdown for workflow categorization on ${doctype}.`,
          reasoning: 'Provides standard operational triage without disrupting ERPNext posting invariants.',
          changes: [
            {
              fieldname: 'custom_priority_status',
              label: 'Priority Status',
              fieldtype: 'Select',
              options: 'Low\nMedium\nHigh\nUrgent',
              reqd: 0,
              read_only: 0,
            },
          ],
        },
        validation: {
          status: 'approved',
          storage_impact: 'ONLINE_ADDITIVE_DDL',
          governance_tier: 'TIER_1_GOVERNED_POLICY',
        },
        ddl_plan: {
          inspectable: true,
          statements: [
            `ALTER TABLE \`tab${doctype}\` ADD COLUMN \`custom_priority_status\` varchar(140) NULL`,
          ],
          is_approved_additive_only: true,
          rejection_reason: null,
        },
        preview_fidelity_notice:
          'Layout, labels, and field controls previewed. ERPNext tax/pricing recalculations and server validations execute on real documents.',
      };
      this.renderProposalCard(mockResult, doctype);
    }

    /**
     * Renders high-fidelity Interactive Proposal Card
     */
    renderProposalCard(data, doctype) {
      const isSuccess = data.success !== false && data.status !== 'REJECTED';
      const proposal = data.proposal || {};
      const changes = proposal.changes || [];
      const fieldDef = changes[0] || {};
      const validation = data.validation || {};
      const ddlPlan = data.ddl_plan || {};
      const cardId = 'exrp-card-' + Math.random().toString(36).substring(2, 9);

      // Gate badge info
      const tier = validation.governance_tier || (isSuccess ? 'TIER_1_GOVERNED_POLICY' : 'TIER_0_IMMUTABLE_INVARIANT');
      const storageImpact = validation.storage_impact || 'ONLINE_ADDITIVE_DDL';
      const isApproved = isSuccess && validation.status !== 'rejected';

      const tierBadgeHtml = isApproved
        ? `<span class="exrp-gate-badge approved">✓ Approved (${tier === 'TIER_1_GOVERNED_POLICY' ? 'Tier 1 Governed Policy' : 'Tier 2 Ordinary Config'})</span>`
        : `<span class="exrp-gate-badge rejected">✕ Rejected (${tier === 'TIER_0_IMMUTABLE_INVARIANT' ? 'Tier 0 Invariant' : 'Policy Gate'})</span>`;

      // SQL statements
      const sqlStatements = (ddlPlan.statements && ddlPlan.statements.length > 0)
        ? ddlPlan.statements.join(';\n') + ';'
        : (fieldDef.fieldname ? `ALTER TABLE \`tab${doctype}\` ADD COLUMN \`${fieldDef.fieldname}\` varchar(140) NULL;` : '-- No physical DDL required --');

      // Table rows for proposed fields
      let tableRows = '';
      if (changes.length > 0) {
        changes.forEach((f) => {
          tableRows += `
            <tr>
              <td class="exrp-code-cell">${escapeHtml(f.fieldname || 'custom_field')}</td>
              <td><strong>${escapeHtml(f.label || f.fieldname)}</strong></td>
              <td><span class="exrp-doctype-badge">${escapeHtml(f.fieldtype || 'Data')}</span></td>
              <td>${escapeHtml((f.options || '-').replace(/\n/g, ', '))}</td>
              <td>${f.reqd ? 'Yes' : 'No'}</td>
            </tr>
          `;
        });
      } else {
        tableRows = `<tr><td colspan="5" style="text-align:center; color: var(--exrp-text-muted);">No field changes in proposal</td></tr>`;
      }

      const cardWrapper = document.createElement('div');
      cardWrapper.className = 'exrp-msg-row exrp-msg-assistant';
      cardWrapper.innerHTML = `
        <div class="exrp-msg-avatar">✨</div>
        <div class="exrp-msg-body">
          <div class="exrp-proposal-card" id="${cardId}">
            <!-- Card Header -->
            <div class="exrp-card-header">
              <div class="exrp-card-title-group">
                <span class="exrp-card-title">Configuration Proposal</span>
                <span class="exrp-intent-badge">${escapeHtml(proposal.intent || 'add_custom_fields')}</span>
              </div>
              <span class="exrp-doctype-badge">${escapeHtml(doctype)}</span>
            </div>

            <!-- Card Body -->
            <div class="exrp-card-body">
              <!-- Summary & Rationale -->
              <div class="exrp-proposal-summary">
                ${escapeHtml(proposal.summary || data.error_message || 'AI Proposed Schema Customization')}
              </div>
              ${
                proposal.reasoning
                  ? `<div class="exrp-proposal-rationale">
                      <div class="exrp-rationale-label">Design Rationale</div>
                      <div>${escapeHtml(proposal.reasoning)}</div>
                    </div>`
                  : ''
              }

              <!-- Field Definition Table -->
              <div class="exrp-field-table-wrapper">
                <table class="exrp-field-table">
                  <thead>
                    <tr>
                      <th>Fieldname</th>
                      <th>Label</th>
                      <th>Type</th>
                      <th>Options</th>
                      <th>Mandatory</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${tableRows}
                  </tbody>
                </table>
              </div>

              <!-- 2-Axis Policy Gate Badge -->
              <div class="exrp-policy-gate-card">
                <div class="exrp-policy-status-row">
                  <span style="font-size: 11.5px; font-weight: 600;">2-Axis Policy Gate:</span>
                  ${tierBadgeHtml}
                </div>
                <div class="exrp-gate-axes">
                  <span class="exrp-axis-pill">📦 Storage: <strong>${escapeHtml(storageImpact)}</strong></span>
                  <span class="exrp-axis-pill">🛡️ Governance: <strong>${escapeHtml(tier)}</strong></span>
                  <span class="exrp-axis-pill">🔒 Fail-Closed Gate: <strong>v2.3</strong></span>
                </div>
              </div>

              <!-- DDL Plan Gate Inspection Card -->
              <div class="exrp-ddl-plan-box">
                <div class="exrp-ddl-header">
                  <span class="exrp-ddl-title">DDL Plan Gate Inspection</span>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span class="exrp-ddl-badge">Safe Additive DDL</span>
                    <button type="button" class="exrp-chip-btn exrp-ddl-copy-btn" data-sql="${escapeHtml(sqlStatements)}" style="padding: 1px 6px; font-size: 10px;">Copy</button>
                  </div>
                </div>
                <pre class="exrp-ddl-code">${escapeHtml(sqlStatements)}</pre>
              </div>

              <!-- Preview Fidelity Notice -->
              <div class="exrp-fidelity-notice">
                <span class="exrp-fidelity-icon">ℹ️</span>
                <span>${escapeHtml(data.preview_fidelity_notice || 'Layout, labels, and field controls previewed. ERPNext tax/pricing recalculations and server validations execute on real documents.')}</span>
              </div>
            </div>

            <!-- Card Actions or Tracker Container -->
            <div class="exrp-card-footer" id="${cardId}-footer">
              ${
                isApproved
                  ? `<div class="exrp-card-actions">
                      <button type="button" class="exrp-btn-action exrp-btn-dismiss" id="${cardId}-btn-dismiss">Dismiss</button>
                      <button type="button" class="exrp-btn-action exrp-btn-deploy" id="${cardId}-btn-deploy">🚀 Deploy to Production</button>
                    </div>`
                  : `<div class="exrp-card-actions">
                      <button type="button" class="exrp-btn-action exrp-btn-dismiss" id="${cardId}-btn-dismiss">Close</button>
                    </div>`
              }
            </div>
          </div>
        </div>
      `;

      this.chatStreamEl.appendChild(cardWrapper);
      this.scrollToBottom();

      // Bind Dismiss & Deploy buttons
      const cardEl = cardWrapper.querySelector(`#${cardId}`);
      const dismissBtn = cardEl.querySelector(`#${cardId}-btn-dismiss`);
      const deployBtn = cardEl.querySelector(`#${cardId}-btn-deploy`);

      if (dismissBtn) {
        dismissBtn.addEventListener('click', () => {
          cardWrapper.style.opacity = '0.5';
          dismissBtn.textContent = 'Dismissed';
          dismissBtn.disabled = true;
          if (deployBtn) deployBtn.style.display = 'none';
        });
      }

      if (deployBtn) {
        deployBtn.addEventListener('click', () => {
          this.executeDurableDeployment(cardId, doctype, proposal, fieldDef);
        });
      }
    }

    /**
     * Executes 4-Stage Animated Deployment Sequence
     * (Acquire Lock -> Dry-Run Gate -> Apply Native DDL -> Verify Snapshot)
     */
    executeDurableDeployment(cardId, doctype, proposal, fieldDef) {
      const footerEl = document.getElementById(`${cardId}-footer`);
      if (!footerEl) return;

      this.isDeploying = true;
      this.sendBtnEl.disabled = true;

      // Render 4-stage deployment tracker HTML
      footerEl.innerHTML = `
        <div class="exrp-deployment-tracker" id="${cardId}-tracker">
          <div class="exrp-tracker-title">
            <span>🛡️ Durable Schema Deployment Sequence</span>
          </div>
          <div class="exrp-stage-list">
            <div class="exrp-stage-item in-progress" id="${cardId}-stage-1">
              <span class="exrp-stage-icon">⚙️</span>
              <span class="exrp-stage-name">1. Acquire Lock (MariaDB Advisory Lock &lt;= 64 chars)</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-2">
              <span class="exrp-stage-icon">2</span>
              <span class="exrp-stage-name">2. Dry-Run Gate (Policy &amp; DDL Invariant Verification)</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-3">
              <span class="exrp-stage-icon">3</span>
              <span class="exrp-stage-name">3. Apply Native DDL (Online Table Mutation)</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-4">
              <span class="exrp-stage-icon">4</span>
              <span class="exrp-stage-name">4. Verify Snapshot (Non-Destructive Reconciliation)</span>
            </div>
          </div>
          <div id="${cardId}-tracker-result"></div>
        </div>
      `;

      const stage1 = footerEl.querySelector(`#${cardId}-stage-1`);
      const stage2 = footerEl.querySelector(`#${cardId}-stage-2`);
      const stage3 = footerEl.querySelector(`#${cardId}-stage-3`);
      const stage4 = footerEl.querySelector(`#${cardId}-stage-4`);
      const resultBox = footerEl.querySelector(`#${cardId}-tracker-result`);

      // Stage progression animator
      const advanceStage = (completedStage, nextStage) => {
        if (completedStage) {
          completedStage.className = 'exrp-stage-item completed';
          completedStage.querySelector('.exrp-stage-icon').textContent = '✓';
        }
        if (nextStage) {
          nextStage.className = 'exrp-stage-item in-progress';
          nextStage.querySelector('.exrp-stage-icon').textContent = '⚙️';
        }
      };

      // Progress through stages with smooth responsive micro-delays
      setTimeout(() => advanceStage(stage1, stage2), 400);
      setTimeout(() => advanceStage(stage2, stage3), 850);

      const handleDeploySuccess = (res) => {
        advanceStage(stage3, stage4);

        setTimeout(() => {
          advanceStage(stage4, null);
          this.isDeploying = false;
          this.sendBtnEl.disabled = !this.inputEl.value.trim();

          resultBox.innerHTML = `
            <div class="exrp-deploy-success-box">
              <span>✓ Field <code>${escapeHtml(fieldDef.fieldname || 'custom_field')}</code> deployed live to production!</span>
            </div>
          `;

          // Show Frappe native alert
          if (window.frappe && typeof window.frappe.show_alert === 'function') {
            window.frappe.show_alert({
              message: __('EXRP: Custom field {0} deployed live to {1}!', [fieldDef.fieldname || 'field', doctype]),
              indicator: 'green',
            });
          }

          // Trigger live form reload without full page refresh (§ADR-001)
          if (window.cur_frm && window.cur_frm.doctype === doctype && typeof window.cur_frm.reload_doc === 'function') {
            window.cur_frm.reload_doc();
          }

          // Update context bar count
          this.updateContext();
          this.appendAssistantMessage(`🎉 <strong>Deployment Successful!</strong> Custom field <code>${escapeHtml(fieldDef.fieldname)}</code> (${escapeHtml(fieldDef.label)}) is now active on <strong>${escapeHtml(doctype)}</strong>.`);
        }, 500);
      };

      const handleDeployFailure = (errReason) => {
        stage3.className = 'exrp-stage-item failed';
        stage3.querySelector('.exrp-stage-icon').textContent = '✕';
        this.isDeploying = false;
        this.sendBtnEl.disabled = !this.inputEl.value.trim();

        resultBox.innerHTML = `
          <div style="margin-top: 8px; padding: 8px 12px; background: var(--exrp-danger-light); border: 1px solid var(--exrp-danger-border); border-radius: var(--exrp-radius-md); font-size: 11.5px; color: var(--exrp-danger); font-weight: 600;">
            ✕ Deployment Blocked: ${escapeHtml(errReason || 'Verification failed')}
          </div>
        `;

        if (window.frappe && typeof window.frappe.msgprint === 'function') {
          window.frappe.msgprint({
            title: __('Deployment Blocked'),
            message: __(errReason || 'Safe deployment gate blocked the operation.'),
            indicator: 'red',
          });
        }
      };

      // Backend call
      if (window.frappe && typeof window.frappe.call === 'function') {
        window.frappe.call({
          method: 'exrp.api.control_plane.apply_configuration_change',
          args: {
            doctype: doctype,
            proposal: proposal,
            field_def: fieldDef,
          },
          callback: (r) => {
            const resp = r ? r.message : null;
            if (resp && resp.status === 'APPLIED') {
              handleDeploySuccess(resp);
            } else {
              handleDeployFailure(resp ? resp.reason : 'Unknown deployment error');
            }
          },
          error: (e) => {
            handleDeployFailure(e ? e.message : 'Network error during deployment');
          },
        });
      } else {
        // Mock deployment success for standalone testing
        setTimeout(() => {
          handleDeploySuccess({
            status: 'APPLIED',
            doctype: doctype,
            fieldname: fieldDef.fieldname,
          });
        }, 1400);
      }
    }
  }

  // Attach to window and Frappe namespace
  window.EXRPAISidecar = EXRPAISidecar;

  // Auto-instantiate when DOM is ready
  function bootstrap() {
    if (!window.exrp.sidecar.instance) {
      window.exrp.sidecar.instance = new EXRPAISidecar();
      window.exrp.sidecar.open = () => window.exrp.sidecar.instance.open();
      window.exrp.sidecar.close = () => window.exrp.sidecar.instance.close();
      window.exrp.sidecar.toggle = () => window.exrp.sidecar.instance.toggle();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();
