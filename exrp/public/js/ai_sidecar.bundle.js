/**
 * EXRP Frappe Desk Embedded AI Sidecar (ADR-001 Rev 2.3)
 * Self-contained vanilla JavaScript class EXRPAISidecar.
 * Injects floating toggle launcher, slide-out drawer, interactive proposal cards,
 * 2-Axis Policy Gate inspection, DDL Plan Gate inspection, and 4-stage durable deployment.
 */

(function () {
  'use strict';

  // Ensure frappe namespace exists
  window.exrp = window.exrp || {};
  window.exrp.sidecar = window.exrp.sidecar || {};
  if (typeof window.frappe !== 'undefined' && typeof window.frappe.provide === 'function') {
    window.frappe.provide('exrp.sidecar');
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
   * Safe Frappe translation helper
   */
  const __ = (typeof window.__ === 'function')
    ? window.__
    : (window.frappe && typeof window.frappe.__ === 'function')
      ? window.frappe.__
      : function (str, params) {
          if (!params) return str;
          if (Array.isArray(params)) {
            let res = str;
            params.forEach((p, i) => { res = res.replace(`{${i}}`, p); });
            return res;
          }
          return str;
        };

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
      this.activePreviewCardId = null;
      this.activePreviewElement = null;

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
            <button class="exrp-btn-settings" id="exrp-btn-settings" title="Configure LLM Provider & Settings (EXRP Settings)" style="background: none; border: 1px solid var(--border-color); cursor: pointer; font-size: 14px; padding: 3px 6px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; color: var(--text-color); line-height: 1;">⚙️</button>
            <span class="exrp-doctype-badge" id="exrp-header-doctype-badge">Desk</span>
            <button class="exrp-btn-close" id="exrp-btn-close" title="Close Sidecar (Esc)">✕</button>
          </div>
        </div>

        <!-- DocType Context Bar -->
        <div class="exrp-context-bar">
          <div class="exrp-context-doctype" style="display: flex; align-items: center; gap: 6px;">
            <span class="exrp-context-indicator" id="exrp-context-indicator"></span>
            <span id="exrp-context-doctype-text" style="display: none;">Sales Order</span>
            <select id="exrp-target-doctype-select" title="Select target DocType to customize" style="font-size: 12px; font-weight: 600; padding: 2px 6px; border-radius: 5px; border: 1px solid var(--border-color, #d1d5db); background: var(--control-bg, #f9fafb); color: var(--text-color, #111827); cursor: pointer;">
              <option value="Sales Order">Sales Order</option>
              <option value="Customer">Customer</option>
              <option value="Delivery Note">Delivery Note</option>
              <option value="Quotation">Quotation</option>
              <option value="Item">Item</option>
              <option value="ToDo">ToDo</option>
              <option value="Note">Note</option>
              <option value="Contact">Contact</option>
              <option value="Address">Address</option>
            </select>
            <button type="button" id="exrp-btn-open-target-doctype" title="Open selected DocType in Desk" style="font-size: 10.5px; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color, #d1d5db); background: transparent; color: var(--primary, #2563eb); cursor: pointer; font-weight: 500;">Open ↗</button>
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
      this.targetDocTypeSelectEl = this.drawerEl.querySelector('#exrp-target-doctype-select');
      this.contextCountEl = this.drawerEl.querySelector('#exrp-context-count');
      this.headerDocTypeEl = this.drawerEl.querySelector('#exrp-header-doctype-badge');
      this.selectedTargetDocType = 'Sales Order';
    }

    /**
     * Binds UI click, keyboard, and resize event handlers
     */
    bindEvents() {
      // Toggle Drawer
      this.launcherEl.addEventListener('click', () => this.toggle());
      this.backdropEl.addEventListener('click', () => this.close());
      this.drawerEl.querySelector('#exrp-btn-close').addEventListener('click', () => this.close());

      // Target DocType Selector
      if (this.targetDocTypeSelectEl) {
        this.targetDocTypeSelectEl.addEventListener('change', (e) => {
          const newDt = e.target.value;
          if (newDt) {
            this.selectedTargetDocType = newDt;
            this.activeDocType = newDt;
            this.clearInPlaceFormPreview();
            this.updateContext();
            this.appendSystemNotice(`Target DocType set to <strong>${escapeHtml(newDt)}</strong>.`);
          }
        });
      }

      const openTargetBtn = this.drawerEl.querySelector('#exrp-btn-open-target-doctype');
      if (openTargetBtn) {
        openTargetBtn.addEventListener('click', () => {
          const dt = this.activeDocType || this.selectedTargetDocType || 'Sales Order';
          if (window.frappe && typeof window.frappe.set_route === 'function') {
            window.frappe.set_route('List', dt);
          }
        });
      }

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

      // Settings button
      const settingsBtn = this.drawerEl.querySelector('#exrp-btn-settings');
      if (settingsBtn) {
        settingsBtn.addEventListener('click', () => this.openSettings());
      }

      // Quick prompt delegation
      this.chatStreamEl.addEventListener('click', (e) => {
        if (e.target.closest('#exrp-link-open-settings')) {
          e.preventDefault();
          this.openSettings();
          return;
        }

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
     * Navigates to EXRP Settings Form
     */
    openSettings() {
      if (window.frappe && typeof window.frappe.set_route === 'function') {
        window.frappe.set_route('Form', 'EXRP Settings');
      } else {
        window.location.href = '/app/exrp-settings';
      }
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
      this.clearInPlaceFormPreview();
      this.drawerEl.classList.remove('exrp-open');
      this.backdropEl.classList.remove('exrp-visible');
    }

    /**
     * Returns true if the given DocType is an internal system or Single DocType
     * that should not overwrite the Copilot's target business DocType.
     */
    isNonCustomizableContextDocType(dt) {
      if (!dt) return true;
      const systemTypes = new Set([
        'EXRP Settings',
        'System Settings',
        'DocType',
        'Custom Field',
        'Property Setter',
        'Workflow',
        'Workflow State',
        'Workflow Action',
        'Report',
        'Workspace',
        'Module Def',
      ]);
      if (systemTypes.has(dt)) return true;
      if (window.cur_frm && window.cur_frm.doctype === dt && window.cur_frm.meta && window.cur_frm.meta.issingle) {
        return true;
      }
      return false;
    }

    /**
     * Resolves currently active DocType from cur_frm or frappe.router,
     * falling back to the user-selected target business DocType when viewing
     * system pages like EXRP Settings or Desk Workspaces.
     */
    getActiveDocType() {
      let pageDt = null;
      if (window.cur_frm && window.cur_frm.doctype) {
        pageDt = window.cur_frm.doctype;
      } else if (window.frappe && typeof window.frappe.get_route === 'function') {
        const route = window.frappe.get_route();
        if (route && (route[0] === 'Form' || route[0] === 'List') && route[1]) {
          pageDt = route[1];
        }
      }
      if (pageDt && !this.isNonCustomizableContextDocType(pageDt)) {
        this.selectedTargetDocType = pageDt;
        return pageDt;
      }
      return this.selectedTargetDocType || 'Sales Order';
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
        if (this.targetDocTypeSelectEl) {
          const exists = Array.from(this.targetDocTypeSelectEl.options).some((opt) => opt.value === dt);
          if (!exists) {
            const newOpt = document.createElement('option');
            newOpt.value = dt;
            newOpt.textContent = dt;
            this.targetDocTypeSelectEl.appendChild(newOpt);
          }
          this.targetDocTypeSelectEl.value = dt;
        }
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
        this.clearInPlaceFormPreview();
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
                <button type="button" class="exrp-chip-btn" data-prompt="Create a 2-stage approval workflow with Manager signoff">🔀 2-Stage Approval</button>
                <button type="button" class="exrp-chip-btn" data-prompt="Create a high-value pending report with customer and grand total">📊 High-Value Report</button>
              </div>
              <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--border-color); font-size: 11px; color: var(--text-muted); display: flex; align-items: center; justify-content: space-between;">
                <span>⚙️ Need to configure Gemini API Key or LLM Provider?</span>
                <a href="#" id="exrp-link-open-settings" style="color: var(--primary); font-weight: 500; text-decoration: underline;">Open Settings</a>
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
              const respData = response.message;
              const prop = respData.proposal || {};
              const isReport = prop.intent === 'create_report' || prop.intent === 'report' || Boolean(prop.report) || Boolean(prop.report_def);
              const isWorkflow = prop.intent === 'create_workflow' || prop.intent === 'workflow_action' || Boolean(prop.workflow) || Boolean(prop.workflow_def);
              if (isReport) {
                this.renderReportProposalCard(prop, respData.validation, { data: respData, doctype: doctype });
              } else if (isWorkflow) {
                this.renderWorkflowProposalCard(prop, respData.validation, { data: respData, doctype: doctype });
              } else {
                this.renderProposalCard(respData, doctype);
              }
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
      const isReportPrompt = /report|builder|virtual table|table preview|high-value/i.test(prompt);
      if (isReportPrompt) {
        const prefix = doctype.replace(/[^A-Za-z]/g, '').substring(0, 3).toUpperCase() || 'DOC';
        const mockRepResult = {
          status: 'PROPOSED',
          success: true,
          proposal: {
            intent: 'create_report',
            target_doctype: doctype,
            summary: `Create high-value pending report with virtual data preview for ${doctype}.`,
            reasoning: 'Provides interactive virtual reporting with deterministic filtering without physical database DDL mutations.',
            report: {
              report_name: `${doctype} High-Value Pending Report`,
              ref_doctype: doctype,
              columns: [
                { fieldname: 'name', label: 'ID', fieldtype: 'Data' },
                { fieldname: 'customer', label: 'Customer', fieldtype: 'Link' },
                { fieldname: 'status', label: 'Status', fieldtype: 'Select' },
                { fieldname: 'grand_total', label: 'Grand Total', fieldtype: 'Currency' },
              ],
              filters: [
                { fieldname: 'status', operator: '=', value: 'Pending' },
                { fieldname: 'grand_total', operator: '>', value: 25000 },
              ],
              sort_by: 'grand_total',
              sort_order: 'desc',
              chart: {
                chart_type: 'Bar',
                x_field: 'customer',
                y_fields: ['grand_total'],
              },
              roles: ['All'],
              add_total_row: true,
            },
          },
          validation: {
            is_valid: true,
            status: 'approved',
            governance_tier: 'TIER_1_GOVERNED_POLICY',
            storage_impact: 'METADATA_ONLY',
            errors: [],
            warnings: [],
            preview_data: [
              { name: `${prefix}-2026-001`, customer: 'Acme Corporation', status: 'Pending', grand_total: 84500.00 },
              { name: `${prefix}-2026-002`, customer: 'Globex Logistics', status: 'Pending', grand_total: 62300.50 },
              { name: `${prefix}-2026-003`, customer: 'Stark Industries', status: 'Pending', grand_total: 45000.00 },
              { name: `${prefix}-2026-004`, customer: 'Wayne Enterprises', status: 'Pending', grand_total: 38200.75 },
              { name: `${prefix}-2026-005`, customer: 'Cyberdyne Systems', status: 'Pending', grand_total: 29800.00 },
            ],
          },
          preview_fidelity_notice:
            'Interactive Virtual Data Table previewed with zero DB DDL schema mutations. Sample records displayed from virtual execution.',
        };
        this.renderReportProposalCard(mockRepResult.proposal, mockRepResult.validation, { data: mockRepResult, doctype });
        return;
      }

      const isWorkflowPrompt = /workflow|approval|state machine|approve/i.test(prompt);
      if (isWorkflowPrompt) {
        const mockWfResult = {
          status: 'PROPOSED',
          success: true,
          proposal: {
            intent: 'create_workflow',
            target_doctype: doctype,
            summary: `Automate multi-tier approval state machine for ${doctype}.`,
            reasoning: 'Enforces segregation of duties and audit compliance with deterministic transitions.',
            workflow: {
              workflow_name: `${doctype} Multi-Tier Approval`,
              document_type: doctype,
              is_active: 1,
              workflow_state_field: 'workflow_state',
              states: [
                { state: 'Draft', doc_status: 0, allow_edit: 'Sales User', style: 'Primary' },
                { state: 'Pending Approval', doc_status: 0, allow_edit: 'Sales Manager', style: 'Warning' },
                { state: 'Approved', doc_status: 1, allow_edit: 'Sales Manager', style: 'Success' },
                { state: 'Rejected', doc_status: 0, allow_edit: 'Sales Manager', style: 'Danger' },
              ],
              transitions: [
                { state: 'Draft', action: 'Submit for Approval', next_state: 'Pending Approval', allowed: 'Sales User' },
                { state: 'Pending Approval', action: 'Approve', next_state: 'Approved', allowed: 'Sales Manager', condition: 'doc.grand_total <= 50000' },
                { state: 'Pending Approval', action: 'Reject', next_state: 'Rejected', allowed: 'Sales Manager' },
              ],
            },
          },
          validation: {
            is_valid: true,
            status: 'approved',
            governance_tier: 'TIER_1_GOVERNED_POLICY',
            storage_impact: 'METADATA_ONLY',
            errors: [],
            warnings: [],
            mermaid_graph: `graph TD\n    Draft["Draft (Draft)"] -->|Submit for Approval [Sales User]| Pending_Approval["Pending Approval (Draft)"]\n    Pending_Approval -->|Approve [Sales Manager]<br><i>doc.grand_total <= 50000</i>| Approved["Approved (Submitted)"]\n    Pending_Approval -->|Reject [Sales Manager]| Rejected["Rejected (Draft)"]`,
          },
          mermaid_graph: `graph TD\n    Draft["Draft (Draft)"] -->|Submit for Approval [Sales User]| Pending_Approval["Pending Approval (Draft)"]\n    Pending_Approval -->|Approve [Sales Manager]<br><i>doc.grand_total <= 50000</i>| Approved["Approved (Submitted)"]\n    Pending_Approval -->|Reject [Sales Manager]| Rejected["Rejected (Draft)"]`,
          preview_fidelity_notice:
            'Workflow state machine previewed with Mermaid diagram. Document transitions and permissions execute on active ERPNext records.',
        };
        this.renderWorkflowProposalCard(mockWfResult.proposal, mockWfResult.validation, { data: mockWfResult, doctype });
        return;
      }

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
     * Injects an in-place visual form preview into cur_frm layout (ADR-001 Rev 2.3 §4.1)
     * Inserts at designated insert_after position without modifying cur_frm.doc or marking dirty.
     *
     * @param {Object} proposal Proposal payload containing target_doctype and field changes
     * @returns {boolean} True if successfully injected, false otherwise
     */
    injectInPlaceFormPreview(proposal) {
      if (!proposal) return false;

      // Extract changes and field definition
      const changes = proposal.changes || (proposal.fieldname ? [proposal] : []);
      const fieldDef = changes[0] || {};
      const targetDocType = proposal.target_doctype || proposal.doctype || this.activeDocType;

      // Verify active DocType form is open
      if (!window.cur_frm || !window.cur_frm.doctype) {
        if (window.frappe && typeof window.frappe.msgprint === 'function') {
          window.frappe.msgprint({
            title: __('Form Context Required'),
            message: __('Please open a {0} document form to preview this field in-place.', [escapeHtml(targetDocType || 'DocType')]),
            indicator: 'orange',
          });
        }
        return false;
      }

      // Verify active form matches target DocType
      if (targetDocType && window.cur_frm.doctype !== targetDocType) {
        if (window.frappe && typeof window.frappe.msgprint === 'function') {
          window.frappe.msgprint({
            title: __('DocType Mismatch'),
            message: __('Current form is {0}, but the proposed field is for {1}. Please navigate to {1} to preview.', [escapeHtml(window.cur_frm.doctype), escapeHtml(targetDocType)]),
            indicator: 'orange',
          });
        }
        return false;
      }

      // Clear any existing preview before injecting
      this.clearInPlaceFormPreview();

      const fieldname = fieldDef.fieldname || 'custom_preview_field';
      const label = fieldDef.label || fieldname;
      const fieldtype = fieldDef.fieldtype || 'Data';
      const options = fieldDef.options || '';
      const reqd = Boolean(fieldDef.reqd);
      const insertAfter = fieldDef.insert_after || proposal.insert_after;
      const description = fieldDef.description || 'Isolated interactive preview. Values entered here are not saved to the document.';

      // Generate input control matching proposed fieldtype
      let inputControlHtml = '';
      if (fieldtype === 'Select') {
        let opts = [];
        if (Array.isArray(options)) {
          opts = options;
        } else if (typeof options === 'string') {
          opts = options.split('\n').map((s) => s.trim()).filter(Boolean);
        }
        inputControlHtml = `
          <select class="form-control" data-preview-field="${escapeHtml(fieldname)}">
            <option value="">Select ${escapeHtml(label)}...</option>
            ${opts.map((opt) => `<option value="${escapeHtml(opt)}">${escapeHtml(opt)}</option>`).join('')}
          </select>
        `;
      } else if (fieldtype === 'Check') {
        inputControlHtml = `
          <div class="checkbox" style="margin-top: 4px;">
            <label style="display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none;">
              <input type="checkbox" style="width: 16px; height: 16px; cursor: pointer;" data-preview-field="${escapeHtml(fieldname)}">
              <span style="font-weight: 500;">${escapeHtml(label)}</span>
            </label>
          </div>
        `;
      } else if (fieldtype === 'Date') {
        const todayIso = new Date().toISOString().slice(0, 10);
        inputControlHtml = `
          <input type="date" class="form-control" value="${todayIso}" data-preview-field="${escapeHtml(fieldname)}">
        `;
      } else if (fieldtype === 'Int' || fieldtype === 'Float' || fieldtype === 'Currency') {
        inputControlHtml = `
          <input type="number" class="form-control" placeholder="0.00" step="any" data-preview-field="${escapeHtml(fieldname)}">
        `;
      } else if (fieldtype === 'Text' || fieldtype === 'Small Text' || fieldtype === 'Long Text') {
        inputControlHtml = `
          <textarea class="form-control" rows="2" placeholder="Type ${escapeHtml(label)} here..." data-preview-field="${escapeHtml(fieldname)}"></textarea>
        `;
      } else {
        // Default: Data / standard text input
        inputControlHtml = `
          <input type="text" class="form-control" placeholder="Type ${escapeHtml(label)} here to test preview..." autocomplete="off" data-preview-field="${escapeHtml(fieldname)}">
        `;
      }

      // Create preview wrapper DOM element
      const wrapperEl = document.createElement('div');
      wrapperEl.className = 'exrp-form-preview-wrapper';
      wrapperEl.id = 'exrp-in-place-form-preview';
      wrapperEl.setAttribute('data-exrp-preview', fieldname);

      wrapperEl.innerHTML = `
        <div class="exrp-form-preview-header">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span class="exrp-preview-badge">[EXRP PREVIEW - NOT SAVED]</span>
            <span class="exrp-preview-hint">Testing sandbox · Zero schema or document mutation</span>
          </div>
          <button type="button" class="exrp-preview-close-btn" title="Exit Visual Preview" aria-label="Exit Visual Preview">✕</button>
        </div>
        <div class="frappe-control form-group" style="margin-bottom: 0;">
          ${
            fieldtype !== 'Check'
              ? `<div class="clearfix" style="margin-bottom: 4px;">
                  <label class="control-label" style="font-size: 12px; font-weight: 600; color: var(--text-color, #1e293b); margin-bottom: 0;">
                    ${escapeHtml(label)}
                    ${reqd ? '<span class="text-danger" style="color: var(--exrp-danger, #ef4444); margin-left: 2px;">*</span>' : ''}
                  </label>
                </div>`
              : ''
          }
          <div class="control-input-wrapper">
            ${inputControlHtml}
          </div>
          <div class="help-box small text-muted" style="margin-top: 4px; font-size: 11px; color: var(--text-muted, #64748b);">
            ${escapeHtml(description)}
          </div>
        </div>
      `;

      // Isolate preview input events so Frappe's cur_frm change/input listeners are NOT triggered
      // and cur_frm.dirty() is NEVER called
      wrapperEl.addEventListener('input', (e) => e.stopPropagation());
      wrapperEl.addEventListener('change', (e) => e.stopPropagation());
      wrapperEl.addEventListener('keydown', (e) => e.stopPropagation());

      // Bind close button on wrapper
      const closeBtn = wrapperEl.querySelector('.exrp-preview-close-btn');
      if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.clearInPlaceFormPreview();
        });
      }

      // Resolve insertion target in cur_frm
      let anchorEl = null;

      // 1. Try resolving via cur_frm.fields_dict[insertAfter]
      if (insertAfter && window.cur_frm.fields_dict && window.cur_frm.fields_dict[insertAfter]) {
        const refField = window.cur_frm.fields_dict[insertAfter];
        anchorEl = (refField.$wrapper && refField.$wrapper[0]) || refField.wrapper || (refField.$wrapper && refField.$wrapper.get ? refField.$wrapper.get(0) : null);
      }

      // 2. Try resolving via data-fieldname attribute within cur_frm wrapper or document
      if (!anchorEl && insertAfter) {
        const scope = window.cur_frm.wrapper || document;
        anchorEl = scope.querySelector(`[data-fieldname="${insertAfter}"]`);
      }

      // 3. Fallback: find the first visible field to insert after
      if (!anchorEl && window.cur_frm.fields_dict) {
        const fieldList = Object.values(window.cur_frm.fields_dict);
        for (const f of fieldList) {
          if (f && f.df && !f.df.hidden && f.df.fieldtype !== 'Section Break' && f.df.fieldtype !== 'Column Break') {
            const el = (f.$wrapper && f.$wrapper[0]) || f.wrapper || (f.$wrapper && f.$wrapper.get ? f.$wrapper.get(0) : null);
            if (el && el.parentNode) {
              anchorEl = el;
              break;
            }
          }
        }
      }

      // Insert into DOM
      if (anchorEl && anchorEl.parentNode) {
        anchorEl.insertAdjacentElement('afterend', wrapperEl);
      } else {
        // Fallback: append inside active form layout or body
        const formBody =
          (window.cur_frm.layout && (window.cur_frm.layout.wrapper || window.cur_frm.layout.body)) ||
          (window.cur_frm.wrapper && window.cur_frm.wrapper.querySelector('.form-layout, .form-page, .form-section')) ||
          document.querySelector('.form-layout .section-body') ||
          document.querySelector('.form-layout') ||
          document.querySelector('.page-body') ||
          window.cur_frm.wrapper;

        if (formBody) {
          formBody.appendChild(wrapperEl);
        } else {
          return false;
        }
      }

      this.activePreviewElement = wrapperEl;

      // Smooth scroll preview into view
      try {
        wrapperEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (err) {
        // ignore scroll error in test environments
      }

      return true;
    }

    /**
     * Cleanly removes any active in-place form preview elements without
     * touching cur_frm.doc or marking the document dirty.
     */
    clearInPlaceFormPreview() {
      const existing = document.querySelectorAll('.exrp-form-preview-wrapper, #exrp-in-place-form-preview');
      existing.forEach((el) => el.remove());

      // Reset all preview buttons in sidecar chat drawer
      document.querySelectorAll('.exrp-btn-preview').forEach((btn) => {
        btn.innerHTML = '👁️ Preview on Form';
        btn.classList.remove('exrp-preview-active');
      });

      this.activePreviewCardId = null;
      this.activePreviewElement = null;
    }

    /**
     * Renders high-fidelity Interactive Proposal Card
     */
    renderProposalCard(data, doctype) {
      const isSuccess = data.success !== false && data.status !== 'REJECTED';
      const proposal = data.proposal || {};
      const isReport = proposal.intent === 'create_report' || proposal.intent === 'report' || Boolean(proposal.report) || Boolean(proposal.report_def);
      if (isReport) {
        return this.renderReportProposalCard(proposal, data.validation, { data, doctype });
      }
      const isWorkflow = proposal.intent === 'create_workflow' || proposal.intent === 'workflow_action' || Boolean(proposal.workflow) || Boolean(proposal.workflow_def);
      if (isWorkflow) {
        return this.renderWorkflowProposalCard(proposal, data.validation, { data, doctype });
      }

      const changes = proposal.changes || [];
      const fieldDef = changes[0] || {};
      const validation = data.validation || {};
      const ddlPlan = data.ddl_plan || {};
      const cardId = 'exrp-card-' + Math.random().toString(36).substring(2, 9);

      // Gate badge info
      const tier = validation.governance_tier || (isSuccess ? 'TIER_1_GOVERNED_POLICY' : 'TIER_0_IMMUTABLE_INVARIANT');
      const storageImpact = validation.storage_impact || 'ONLINE_ADDITIVE_DDL';
      const isApproved = isSuccess && validation.status !== 'rejected';
      const isDdlApproved = ddlPlan.is_approved_additive_only !== false && isApproved;

      const tierBadgeHtml = isApproved
        ? `<span class="exrp-gate-badge approved">✓ Approved (${tier === 'TIER_1_GOVERNED_POLICY' ? 'Tier 1 Governed Policy' : 'Tier 2 Ordinary Config'})</span>`
        : `<span class="exrp-gate-badge rejected">✕ Rejected (${tier === 'TIER_0_IMMUTABLE_INVARIANT' ? 'Tier 0 Invariant' : 'Policy Gate'})</span>`;

      const ddlBadgeHtml = isDdlApproved
        ? `<span class="exrp-ddl-badge">Safe Additive DDL</span>`
        : `<span class="exrp-ddl-badge" style="background: rgba(239, 68, 68, 0.18); color: #f87171;">Rejected by Gate</span>`;

      // SQL statements
      const sqlStatements = (ddlPlan.statements && ddlPlan.statements.length > 0)
        ? ddlPlan.statements.join(';\n') + ';'
        : (ddlPlan.rejection_reason
          ? `-- ${ddlPlan.rejection_reason}`
          : (fieldDef.fieldname ? `ALTER TABLE \`tab${doctype}\` ADD COLUMN \`${fieldDef.fieldname}\` varchar(140) NULL;` : '-- No physical DDL required --'));

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
                    ${ddlBadgeHtml}
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
                      <button type="button" class="exrp-btn-action exrp-btn-preview" id="${cardId}-btn-preview" title="Test field preview in-place on current form">👁️ Preview on Form</button>
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

      // Bind Preview, Dismiss & Deploy buttons
      const cardEl = cardWrapper.querySelector(`#${cardId}`);
      const previewBtn = cardEl.querySelector(`#${cardId}-btn-preview`);
      const dismissBtn = cardEl.querySelector(`#${cardId}-btn-dismiss`);
      const deployBtn = cardEl.querySelector(`#${cardId}-btn-deploy`);

      if (previewBtn) {
        previewBtn.addEventListener('click', () => {
          if (this.activePreviewCardId === cardId) {
            this.clearInPlaceFormPreview();
          } else {
            this.clearInPlaceFormPreview();
            const injected = this.injectInPlaceFormPreview(proposal);
            if (injected) {
              this.activePreviewCardId = cardId;
              previewBtn.innerHTML = '✕ Exit Preview';
              previewBtn.classList.add('exrp-preview-active');
            }
          }
        });
      }

      if (dismissBtn) {
        dismissBtn.addEventListener('click', () => {
          this.clearInPlaceFormPreview();
          cardWrapper.style.opacity = '0.5';
          dismissBtn.textContent = 'Dismissed';
          dismissBtn.disabled = true;
          if (previewBtn) previewBtn.style.display = 'none';
          if (deployBtn) deployBtn.style.display = 'none';
        });
      }

      if (deployBtn) {
        deployBtn.addEventListener('click', () => {
          this.clearInPlaceFormPreview();
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

          const deploymentId = (res && res.deployment_id) || (proposal && proposal.deployment_id) || ('dep_' + Math.random().toString(36).substring(2, 10));
          const isPropertySetter = Boolean(
            (proposal && (proposal.intent === 'property_setter' || proposal.intent === 'update_field_property' || proposal.change_type === 'property_setter' || proposal.operation === 'property_setter')) ||
            (fieldDef && (fieldDef.property || fieldDef.property_type))
          );

          resultBox.innerHTML = `
            <div class="exrp-deploy-success-box">
              <div class="exrp-deploy-success-details">
                <div class="exrp-deploy-success-msg">
                  <span>✓ ${isPropertySetter ? 'Property Setter' : 'Custom Field'} <code>${escapeHtml(fieldDef.fieldname || 'custom_field')}</code> deployed live to production!</span>
                  <span class="exrp-quarantine-badge" id="${cardId}-quarantine-badge" style="display: none;"></span>
                </div>
                <button type="button" class="exrp-btn-action exrp-btn-revert" id="${cardId}-btn-revert" title="Revert or quarantine this configuration change safely" data-deployment-id="${escapeHtml(deploymentId)}">
                  ↩️ Revert Changes
                </button>
              </div>
            </div>
          `;

          // Bind 1-Click Rollback / Quarantine button handler
          const revertBtn = resultBox.querySelector(`#${cardId}-btn-revert`);
          if (revertBtn) {
            revertBtn.addEventListener('click', () => {
              const confirmMessage = isPropertySetter
                ? 'This will restore the field property to its original baseline state.'
                : 'This will quarantine and hide the field (hidden=1) preserving all historical data without dropping database columns.';

              const executeRevert = () => {
                revertBtn.disabled = true;
                revertBtn.innerHTML = '⏳ Reverting...';

                const onRevertSuccess = (revertResult) => {
                  revertBtn.innerHTML = '✓ Reverted';
                  revertBtn.classList.add('exrp-reverted');
                  revertBtn.disabled = true;

                  const badgeEl = resultBox.querySelector(`#${cardId}-quarantine-badge`);
                  if (badgeEl) {
                    badgeEl.textContent = isPropertySetter ? 'Restored Baseline' : 'Quarantined (hidden=1)';
                    badgeEl.style.display = 'inline-flex';
                  }

                  // 1. Triggers cur_frm.reload_doc()
                  if (window.cur_frm && window.cur_frm.doctype === doctype && typeof window.cur_frm.reload_doc === 'function') {
                    window.cur_frm.reload_doc();
                  }

                  // 2. Updates context count
                  this.updateContext();

                  // 3. Alerts user
                  if (window.frappe && typeof window.frappe.show_alert === 'function') {
                    window.frappe.show_alert({
                      message: __('EXRP: Configuration change reverted and quarantined successfully.'),
                      indicator: 'orange',
                    });
                  }

                  this.appendAssistantMessage(
                    `↩️ <strong>Rollback Executed:</strong> Configuration for <code>${escapeHtml(fieldDef.fieldname || doctype)}</code> has been safely reverted. ${
                      isPropertySetter
                        ? 'Field property restored to its original baseline state.'
                        : 'Custom field marked <code>hidden=1, reqd=0</code> (quarantined; historical DB columns preserved without drops).'
                    }`
                  );
                };

                const onRevertFailure = (err) => {
                  revertBtn.disabled = false;
                  revertBtn.innerHTML = '↩️ Revert Changes';
                  const msg = (err && (err.message || err.reason)) || 'Failed to revert configuration change.';
                  if (window.frappe && typeof window.frappe.msgprint === 'function') {
                    window.frappe.msgprint({
                      title: __('Revert Blocked'),
                      message: __(msg),
                      indicator: 'red',
                    });
                  } else {
                    alert(`Revert Failed: ${msg}`);
                  }
                };

                // Backend RPC call
                if (window.frappe && typeof window.frappe.call === 'function') {
                  window.frappe.call({
                    method: 'exrp.api.control_plane.revert_configuration_change',
                    args: {
                      deployment_id: deploymentId,
                    },
                    callback: (r) => {
                      const outcome = r ? r.message : null;
                      if (outcome && (outcome.status === 'REVERTED' || outcome.status === 'QUARANTINED' || outcome.success !== false)) {
                        onRevertSuccess(outcome);
                      } else {
                        onRevertFailure(outcome || { message: 'Revert rejected by control plane' });
                      }
                    },
                    error: (e) => {
                      onRevertFailure(e);
                    },
                  });
                } else {
                  // Standalone / offline mock fallback
                  setTimeout(() => {
                    onRevertSuccess({ status: 'QUARANTINED', success: true });
                  }, 500);
                }
              };

              // Native Frappe confirmation dialog
              if (window.frappe && typeof window.frappe.confirm === 'function') {
                window.frappe.confirm(confirmMessage, executeRevert);
              } else {
                if (window.confirm(confirmMessage)) {
                  executeRevert();
                }
              }
            });
          }

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

    /**
     * Renders Phase 3 Declarative Workflow State Machine Preview Card
     * (§10 ADR-001 Rev 2.3 & ADR-006)
     *
     * @param {Object} proposal Proposal payload containing intent and workflow definition
     * @param {Object} validation State machine validation and safety result
     * @param {Object} [options] Context options including doctype and raw response data
     */
    renderWorkflowProposalCard(proposal, validation, options = {}) {
      let data = options.data || {};
      let doctype = options.doctype || this.activeDocType || 'Sales Order';

      // Support polymorphic signature: renderWorkflowProposalCard(data, doctype)
      if (proposal && proposal.proposal && !proposal.intent && !proposal.workflow) {
        data = proposal;
        doctype = validation || options.doctype || this.activeDocType || 'Sales Order';
        proposal = data.proposal || {};
        validation = data.validation || {};
      }

      validation = validation || data.validation || {};
      const workflowDef = proposal.workflow || proposal.workflow_def || (proposal.states && proposal.transitions ? proposal : {});
      const targetDocType = workflowDef.document_type || proposal.target_doctype || doctype;
      const workflowName = workflowDef.workflow_name || proposal.workflow_name || `${targetDocType} Multi-Tier Approval`;
      const states = workflowDef.states || [];
      const transitions = workflowDef.transitions || [];
      const cardId = 'exrp-wf-card-' + Math.random().toString(36).substring(2, 9);
      const deploymentId = (data && data.deployment_id) || (proposal && proposal.deployment_id) || ('dep_wf_' + Math.random().toString(36).substring(2, 10));

      const isSuccess = data.success !== false && data.status !== 'REJECTED';
      const isValid = Boolean(
        validation &&
        (validation.is_valid === true || validation.status === 'approved') &&
        (!validation.errors || validation.errors.length === 0)
      );

      const errorMessage = (validation.errors && validation.errors.length > 0)
        ? validation.errors.join('; ')
        : (validation.error || data.error_message || 'Workflow state machine invariants violated.');

      // State Machine Safety Verification Badge
      const safetyBadgeHtml = isValid
        ? `<div class="exrp-wf-safety-badge verified">
             <span class="exrp-safety-icon">✓</span>
             <span>STATE MACHINE VERIFIED - REACHABLE &amp; DEADLOCK FREE</span>
           </div>`
        : `<div class="exrp-wf-safety-badge rejected">
             <span class="exrp-safety-icon">✕</span>
             <span>REJECTED: ${escapeHtml(errorMessage)}</span>
           </div>`;

      // State List Chips / Flow
      let statesHtml = '';
      if (states.length > 0) {
        states.forEach((st) => {
          const docStatus = Number(st.doc_status !== undefined ? st.doc_status : 0);
          const style = (st.style || '').toLowerCase();
          let stateClass = 'exrp-state-draft';
          let docStatusLabel = 'Draft (0)';

          if (docStatus === 1 || style === 'success' || (st.state && st.state.toLowerCase().includes('approve'))) {
            stateClass = 'exrp-state-approved';
            docStatusLabel = 'Approved (1)';
          } else if (docStatus === 2 || style === 'danger' || (st.state && (st.state.toLowerCase().includes('reject') || st.state.toLowerCase().includes('cancel')))) {
            stateClass = 'exrp-state-rejected';
            docStatusLabel = docStatus === 2 ? 'Cancelled (2)' : 'Rejected (0)';
          } else if (style === 'warning' || (st.state && st.state.toLowerCase().includes('pending'))) {
            stateClass = 'exrp-state-warning';
            docStatusLabel = 'Pending (0)';
          }

          statesHtml += `
            <div class="exrp-state-chip ${stateClass}">
              <div class="exrp-state-chip-header">
                <span class="exrp-state-name" title="${escapeHtml(st.state)}">${escapeHtml(st.state)}</span>
                <span class="exrp-state-docstatus-pill">${escapeHtml(docStatusLabel)}</span>
              </div>
              <div class="exrp-state-chip-meta">
                <span class="exrp-state-edit-role" title="Role permitted to edit in this state">
                  ✏️ Edit: <strong>${escapeHtml(st.allow_edit || 'All')}</strong>
                </span>
              </div>
            </div>
          `;
        });
      } else {
        statesHtml = `<div class="exrp-empty-states" style="color: var(--exrp-text-muted); font-size: 12px; padding: 6px;">No states defined in workflow proposal.</div>`;
      }

      // Transitions Table / Flow Cards
      let transitionsHtml = '';
      if (transitions.length > 0) {
        transitions.forEach((tr) => {
          const hasCondition = Boolean(tr.condition && String(tr.condition).trim());
          const allowsSelfApproval = Boolean(tr.allow_self_approval === 1 || tr.allow_self_approval === true);
          transitionsHtml += `
            <div class="exrp-transition-row">
              <div class="exrp-transition-flow">
                <span class="exrp-state-pill from">${escapeHtml(tr.state)}</span>
                <span class="exrp-transition-connector">
                  <span class="exrp-arrow-line"></span>
                  <span class="exrp-action-pill" title="Transition Action">Action: <strong>${escapeHtml(tr.action)}</strong></span>
                  <span class="exrp-arrow-head">▶</span>
                </span>
                <span class="exrp-state-pill to">${escapeHtml(tr.next_state)}</span>
              </div>
              <div class="exrp-transition-badges">
                <span class="exrp-role-pill" title="Role allowed to execute transition">👤 ${escapeHtml(tr.allowed || 'All')}</span>
                ${hasCondition ? `<span class="exrp-condition-pill" title="Transition Condition">⚡ <code>${escapeHtml(tr.condition)}</code></span>` : ''}
                ${allowsSelfApproval ? `<span class="exrp-self-approval-pill" title="Self-approval permitted">🛡️ Self-Approval Allowed</span>` : ''}
              </div>
            </div>
          `;
        });
      } else {
        transitionsHtml = `<div class="exrp-empty-transitions" style="color: var(--exrp-text-muted); font-size: 12px; padding: 6px;">No transitions defined.</div>`;
      }

      // Visual Diagram Preview (Mermaid)
      const mermaidGraph = validation.mermaid_graph || data.mermaid_graph || (data.ddl_plan && data.ddl_plan.mermaid_graph) || '';

      const cardWrapper = document.createElement('div');
      cardWrapper.className = 'exrp-msg-row exrp-msg-assistant';
      cardWrapper.innerHTML = `
        <div class="exrp-msg-avatar">✨</div>
        <div class="exrp-msg-body">
          <div class="exrp-workflow-card" id="${cardId}">
            <!-- Workflow Header -->
            <div class="exrp-card-header">
              <div class="exrp-card-title-group">
                <span class="exrp-card-title">${escapeHtml(workflowName)}</span>
                <span class="exrp-intent-badge">${escapeHtml(proposal.intent || 'create_workflow')}</span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                <span class="exrp-doctype-badge">${escapeHtml(targetDocType)}</span>
                <div id="${cardId}-header-badge">
                  <span class="exrp-wf-preview-badge">Draft Preview</span>
                </div>
              </div>
            </div>

            <!-- Card Body -->
            <div class="exrp-card-body">
              <!-- Summary & Rationale -->
              <div class="exrp-proposal-summary">
                ${escapeHtml(proposal.summary || data.error_message || 'AI Proposed Declarative Workflow State Machine')}
              </div>
              ${
                proposal.reasoning
                  ? `<div class="exrp-proposal-rationale">
                      <div class="exrp-rationale-label">Design Rationale</div>
                      <div>${escapeHtml(proposal.reasoning)}</div>
                    </div>`
                  : ''
              }

              <!-- State Machine Safety Verification Badge -->
              ${safetyBadgeHtml}

              <!-- State List Chips / Flow -->
              <div>
                <div class="exrp-section-label">
                  <span>Workflow States &amp; Roles</span>
                  <span style="font-size: 10px; font-weight: normal; color: var(--exrp-text-muted);">${states.length} states</span>
                </div>
                <div class="exrp-workflow-states">
                  ${statesHtml}
                </div>
              </div>

              <!-- Transitions Table / Flow Cards -->
              <div>
                <div class="exrp-workflow-transitions">
                  <div class="exrp-transitions-header">
                    <span class="exrp-transitions-title">State Transitions &amp; Permission Rules</span>
                    <span class="exrp-transitions-count">${transitions.length} transitions</span>
                  </div>
                  <div class="exrp-transition-list">
                    ${transitionsHtml}
                  </div>
                </div>
              </div>

              <!-- Visual Diagram Preview (Mermaid) -->
              ${
                mermaidGraph
                  ? `<div class="exrp-mermaid-container" id="${cardId}-mermaid-container">
                      <div class="exrp-mermaid-header">
                        <span class="exrp-mermaid-title">📊 State Machine Flowchart</span>
                        <div class="exrp-mermaid-controls">
                          <button type="button" class="exrp-chip-btn" id="${cardId}-btn-toggle-diagram">Collapse</button>
                          <button type="button" class="exrp-chip-btn" id="${cardId}-btn-copy-diagram">Copy Mermaid</button>
                        </div>
                      </div>
                      <div class="exrp-mermaid-body" id="${cardId}-mermaid-body">
                        <div class="exrp-mermaid-svg-container" id="${cardId}-mermaid-svg" style="display: none;"></div>
                        <pre class="exrp-mermaid-code" id="${cardId}-mermaid-code">${escapeHtml(mermaidGraph)}</pre>
                      </div>
                    </div>`
                  : ''
              }

              <!-- Preview Fidelity Notice -->
              <div class="exrp-fidelity-notice">
                <span class="exrp-fidelity-icon">ℹ️</span>
                <span>${escapeHtml(data.preview_fidelity_notice || 'Workflow state machine previewed with Mermaid diagram. Document transitions and permissions execute on active ERPNext records.')}</span>
              </div>
            </div>

            <!-- Card Actions -->
            <div class="exrp-card-footer" id="${cardId}-footer">
              ${
                isValid
                  ? `<div class="exrp-card-actions">
                      <button type="button" class="exrp-btn-action exrp-btn-dismiss" id="${cardId}-btn-dismiss">Dismiss</button>
                      <button type="button" class="exrp-btn-action exrp-btn-deploy" id="${cardId}-btn-deploy">🚀 Deploy Workflow to Production</button>
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

      // Bind Mermaid Controls
      const cardEl = cardWrapper.querySelector(`#${cardId}`);
      if (mermaidGraph) {
        const toggleBtn = cardEl.querySelector(`#${cardId}-btn-toggle-diagram`);
        const copyBtn = cardEl.querySelector(`#${cardId}-btn-copy-diagram`);
        const mermaidBody = cardEl.querySelector(`#${cardId}-mermaid-body`);
        const mermaidCode = cardEl.querySelector(`#${cardId}-mermaid-code`);
        const mermaidSvg = cardEl.querySelector(`#${cardId}-mermaid-svg`);

        if (toggleBtn && mermaidBody) {
          let collapsed = false;
          toggleBtn.addEventListener('click', () => {
            collapsed = !collapsed;
            mermaidBody.style.display = collapsed ? 'none' : 'block';
            toggleBtn.textContent = collapsed ? 'Expand' : 'Collapse';
          });
        }

        if (copyBtn) {
          copyBtn.addEventListener('click', () => {
            const code = mermaidGraph;
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(code).then(() => {
                copyBtn.textContent = '✓ Copied';
                setTimeout(() => { copyBtn.textContent = 'Copy Mermaid'; }, 1800);
              });
            } else {
              const ta = document.createElement('textarea');
              ta.value = code;
              document.body.appendChild(ta);
              ta.select();
              document.execCommand('copy');
              ta.remove();
              copyBtn.textContent = '✓ Copied';
              setTimeout(() => { copyBtn.textContent = 'Copy Mermaid'; }, 1800);
            }
          });
        }

        // Live SVG rendering if window.mermaid is present
        if (window.mermaid && mermaidSvg) {
          try {
            const svgRenderId = 'mermaid-svg-' + Math.random().toString(36).substring(2, 9);
            if (typeof window.mermaid.render === 'function') {
              window.mermaid.render(svgRenderId, mermaidGraph, (svgCode) => {
                mermaidSvg.innerHTML = svgCode;
                mermaidSvg.style.display = 'block';
                if (mermaidCode) mermaidCode.style.display = 'none';
              });
            }
          } catch (e) {
            // Keep monospace code visible on error
          }
        }
      }

      // Bind Dismiss & Deploy buttons
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
          this.executeWorkflowDeployment(cardId, targetDocType, proposal, workflowDef, validation);
        });
      }
    }

    /**
     * Executes Animated 4-Stage Workflow State Machine Deployment
     * 1. Validate Reachability & Deadlock Safety
     * 2. Acquire Site Advisory Lock
     * 3. Register Workflow States & Transitions
     * 4. Activate Workflow on <DocType>
     */
    executeWorkflowDeployment(cardId, doctype, proposal, workflowDef, validation) {
      const footerEl = document.getElementById(`${cardId}-footer`);
      if (!footerEl) return;

      this.isDeploying = true;
      this.sendBtnEl.disabled = true;

      // Render 4-stage workflow deployment tracker HTML
      footerEl.innerHTML = `
        <div class="exrp-deployment-tracker" id="${cardId}-wf-tracker">
          <div class="exrp-tracker-title">
            <span>🛡️ Declarative Workflow Deployment Sequence</span>
          </div>
          <div class="exrp-stage-list">
            <div class="exrp-stage-item in-progress" id="${cardId}-stage-1">
              <span class="exrp-stage-icon">⚙️</span>
              <span class="exrp-stage-name">1. Validate Reachability &amp; Deadlock Safety</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-2">
              <span class="exrp-stage-icon">2</span>
              <span class="exrp-stage-name">2. Acquire Site Advisory Lock</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-3">
              <span class="exrp-stage-icon">3</span>
              <span class="exrp-stage-name">3. Register Workflow States &amp; Transitions</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-4">
              <span class="exrp-stage-icon">4</span>
              <span class="exrp-stage-name">4. Activate Workflow on ${escapeHtml(doctype)}</span>
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

      // Progress through initial verification stages
      setTimeout(() => advanceStage(stage1, stage2), 350);
      setTimeout(() => advanceStage(stage2, stage3), 750);

      const targetDocType = (window.cur_frm && window.cur_frm.doctype) ? window.cur_frm.doctype : (workflowDef.document_type || proposal.target_doctype || doctype);
      const deploymentId = (proposal && proposal.deployment_id) || ('dep_wf_' + Math.random().toString(36).substring(2, 10));
      const deployedWfPayload = proposal.workflow || workflowDef;

      const handleDeploySuccess = (res) => {
        advanceStage(stage3, stage4);

        setTimeout(() => {
          advanceStage(stage4, null);
          this.isDeploying = false;
          this.sendBtnEl.disabled = !this.inputEl.value.trim();

          const activeDepId = (res && res.deployment_id) || deploymentId;
          const activeWfName = (res && res.workflow_name) || workflowDef.workflow_name || `${targetDocType} Multi-Tier Approval`;

          // Update header status badge to WORKFLOW ACTIVE
          const headerBadge = document.getElementById(`${cardId}-header-badge`);
          if (headerBadge) {
            headerBadge.innerHTML = `<span class="exrp-workflow-status-badge active"><span class="exrp-pulse-dot"></span> WORKFLOW ACTIVE</span>`;
          }

          resultBox.innerHTML = `
            <div class="exrp-deploy-success-box">
              <div class="exrp-deploy-success-details">
                <div class="exrp-deploy-success-msg">
                  <span class="exrp-workflow-status-badge active"><span class="exrp-pulse-dot"></span> WORKFLOW ACTIVE</span>
                  <span>✓ Workflow <code>${escapeHtml(activeWfName)}</code> is now active on <strong>${escapeHtml(targetDocType)}</strong>!</span>
                </div>
                <button type="button" class="exrp-btn-action exrp-btn-revert" id="${cardId}-btn-revert" title="Deactivate or restore previous baseline safely" data-deployment-id="${escapeHtml(activeDepId)}">
                  ↩️ Deactivate / Revert Workflow
                </button>
              </div>
            </div>
          `;

          // Bind 1-Click Workflow Rollback UI
          const revertBtn = resultBox.querySelector(`#${cardId}-btn-revert`);
          if (revertBtn) {
            revertBtn.addEventListener('click', () => {
              const confirmMessage = "Are you sure you want to revert this workflow? This will safely deactivate the state machine (is_active=0) or restore the previous workflow baseline, preserving all existing document records without loss.";

              const executeRevert = () => {
                revertBtn.disabled = true;
                revertBtn.innerHTML = '⏳ Deactivating Workflow...';

                const onRevertSuccess = (revertResult) => {
                  revertBtn.innerHTML = '✓ Workflow Deactivated';
                  revertBtn.classList.add('exrp-reverted');
                  revertBtn.disabled = true;

                  if (headerBadge) {
                    headerBadge.innerHTML = `<span class="exrp-workflow-status-badge deactivated">WORKFLOW DEACTIVATED</span>`;
                  }

                  const activeBadges = resultBox.querySelectorAll('.exrp-workflow-status-badge.active');
                  activeBadges.forEach((b) => {
                    b.className = 'exrp-workflow-status-badge deactivated';
                    b.innerHTML = 'WORKFLOW DEACTIVATED';
                  });

                  // 1. Triggers cur_frm.reload_doc()
                  if (window.cur_frm && window.cur_frm.doctype === targetDocType && typeof window.cur_frm.reload_doc === 'function') {
                    window.cur_frm.reload_doc();
                  }

                  // 2. Updates context count
                  this.updateContext();

                  // 3. Alerts user
                  if (window.frappe && typeof window.frappe.show_alert === 'function') {
                    window.frappe.show_alert({
                      message: __('EXRP: Workflow state machine safely deactivated / baseline restored.'),
                      indicator: 'orange',
                    });
                  }

                  this.appendAssistantMessage(
                    `↩️ <strong>Workflow Reverted:</strong> State machine for <strong>${escapeHtml(targetDocType)}</strong> has been safely deactivated (is_active=0) and baseline restored without record loss.`
                  );
                };

                const onRevertFailure = (err) => {
                  revertBtn.disabled = false;
                  revertBtn.innerHTML = '↩️ Deactivate / Revert Workflow';
                  const msg = (err && (err.message || err.reason)) || 'Failed to revert workflow state machine.';
                  if (window.frappe && typeof window.frappe.msgprint === 'function') {
                    window.frappe.msgprint({
                      title: __('Workflow Rollback Blocked'),
                      message: __(msg),
                      indicator: 'red',
                    });
                  } else {
                    alert(`Workflow Rollback Failed: ${msg}`);
                  }
                };

                // RPC call to revert_configuration_change
                if (window.frappe && typeof window.frappe.call === 'function') {
                  window.frappe.call({
                    method: 'exrp.api.control_plane.revert_configuration_change',
                    args: {
                      deployment_id: activeDepId,
                    },
                    callback: (r) => {
                      const outcome = r ? r.message : null;
                      if (outcome && (outcome.status === 'ROLLED_BACK' || outcome.disposition === 'WORKFLOW_DEACTIVATED' || outcome.success !== false)) {
                        onRevertSuccess(outcome);
                      } else {
                        onRevertFailure(outcome || { message: 'Workflow rollback rejected by control plane' });
                      }
                    },
                    error: (e) => onRevertFailure(e),
                  });
                } else {
                  // Mock rollback fallback
                  setTimeout(() => {
                    onRevertSuccess({ status: 'ROLLED_BACK', disposition: 'WORKFLOW_DEACTIVATED', success: true });
                  }, 500);
                }
              };

              // Native Frappe confirmation dialog
              if (window.frappe && typeof window.frappe.confirm === 'function') {
                window.frappe.confirm(confirmMessage, executeRevert);
              } else if (window.confirm(confirmMessage)) {
                executeRevert();
              }
            });
          }

          // Show Frappe native alert
          if (window.frappe && typeof window.frappe.show_alert === 'function') {
            window.frappe.show_alert({
              message: __('EXRP: Workflow {0} activated on {1}!', [activeWfName, targetDocType]),
              indicator: 'green',
            });
          }

          // Trigger live form reload without full page refresh (§ADR-001)
          if (window.cur_frm && window.cur_frm.doctype === targetDocType && typeof window.cur_frm.reload_doc === 'function') {
            window.cur_frm.reload_doc();
          }

          // Update context
          this.updateContext();
          this.appendAssistantMessage(
            `🎉 <strong>Workflow Activated!</strong> State machine <code>${escapeHtml(activeWfName)}</code> is now active on <strong>${escapeHtml(targetDocType)}</strong>.`
          );
        }, 400);
      };

      const handleDeployFailure = (errReason) => {
        stage3.className = 'exrp-stage-item failed';
        stage3.querySelector('.exrp-stage-icon').textContent = '✕';
        this.isDeploying = false;
        this.sendBtnEl.disabled = !this.inputEl.value.trim();

        resultBox.innerHTML = `
          <div style="margin-top: 8px; padding: 8px 12px; background: var(--exrp-danger-light); border: 1px solid var(--exrp-danger-border); border-radius: var(--exrp-radius-md); font-size: 11.5px; color: var(--exrp-danger); font-weight: 600;">
            ✕ Workflow Deployment Blocked: ${escapeHtml(errReason || 'State machine safety verification failed')}
          </div>
        `;

        if (window.frappe && typeof window.frappe.msgprint === 'function') {
          window.frappe.msgprint({
            title: __('Workflow Deployment Blocked'),
            message: __(errReason || 'Safe workflow deployment gate blocked the operation.'),
            indicator: 'red',
          });
        }
      };

      // Backend call to apply_workflow_change
      if (window.frappe && typeof window.frappe.call === 'function') {
        window.frappe.call({
          method: 'exrp.api.control_plane.apply_workflow_change',
          args: {
            doctype: targetDocType,
            deployment_id: deploymentId,
            workflow_def: deployedWfPayload,
          },
          callback: (r) => {
            const resp = r ? r.message : null;
            if (resp && (resp.status === 'APPLIED' || resp.success !== false)) {
              handleDeploySuccess(resp);
            } else {
              handleDeployFailure(resp ? (resp.reason || resp.disposition) : 'Unknown deployment error');
            }
          },
          error: (e) => {
            handleDeployFailure(e ? (e.message || e.toString()) : 'Network error during workflow deployment');
          },
        });
      } else {
        // Mock deployment success for standalone testing
        setTimeout(() => {
          handleDeploySuccess({
            status: 'APPLIED',
            disposition: 'WORKFLOW_STATE_MACHINE_ACTIVATED',
            workflow_name: workflowDef.workflow_name,
            doctype: targetDocType,
          });
        }, 1200);
      }
    }

    /**
     * Renders high-fidelity Declarative Report Builder Preview Card (PRD-001, ADR-001 §10, ADR-006)
     *
     * @param {Object} proposal Declarative Report specification
     * @param {Object} validation Safety and preview validation result
     * @param {Object} [options] Context options including doctype and raw response data
     */
    renderReportProposalCard(proposal, validation, options = {}) {
      let data = options.data || {};
      let doctype = options.doctype || this.activeDocType || 'Sales Order';

      // Support polymorphic signature: renderReportProposalCard(data, doctype)
      if (proposal && proposal.proposal && !proposal.intent && !proposal.report) {
        data = proposal;
        doctype = validation || options.doctype || this.activeDocType || 'Sales Order';
        proposal = data.proposal || {};
        validation = data.validation || {};
      }

      validation = validation || data.validation || {};
      const reportDef = proposal.report || proposal.report_def || (proposal.columns ? proposal : {});
      const targetDocType = reportDef.ref_doctype || reportDef.document_type || proposal.target_doctype || doctype;
      const reportName = reportDef.report_name || proposal.report_name || `${targetDocType} High-Value Pending Report`;
      const rawColumns = reportDef.columns || [];
      const filters = reportDef.filters || [];
      const sortBy = reportDef.sort_by || 'modified';
      const sortOrder = (reportDef.sort_order || 'desc').toUpperCase();
      const chart = reportDef.chart || null;
      const cardId = 'exrp-rep-card-' + Math.random().toString(36).substring(2, 9);
      const deploymentId = (data && data.deployment_id) || (proposal && proposal.deployment_id) || ('dep_rep_' + Math.random().toString(36).substring(2, 10));

      const isSuccess = data.success !== false && data.status !== 'REJECTED';
      const isValid = Boolean(
        validation &&
        (validation.is_valid === true || validation.status === 'approved') &&
        (!validation.errors || validation.errors.length === 0)
      );

      const errorMessage = (validation.errors && validation.errors.length > 0)
        ? validation.errors.join('; ')
        : (validation.error || data.error_message || 'Report definition invariants violated.');

      // Normalize columns
      const normalizedColumns = rawColumns.map((c) => {
        if (typeof c === 'string') {
          return { fieldname: c, label: c, fieldtype: 'Data' };
        }
        return {
          fieldname: c.fieldname || 'field',
          label: c.label || c.fieldname || 'Field',
          fieldtype: c.fieldtype || 'Data',
        };
      });
      if (normalizedColumns.length === 0) {
        normalizedColumns.push(
          { fieldname: 'name', label: 'ID', fieldtype: 'Data' },
          { fieldname: 'customer', label: 'Customer', fieldtype: 'Link' },
          { fieldname: 'status', label: 'Status', fieldtype: 'Select' },
          { fieldname: 'grand_total', label: 'Grand Total', fieldtype: 'Currency' }
        );
      }

      // Check numeric/currency column
      const isNumericCol = (col) => {
        const ft = (col.fieldtype || '').toLowerCase();
        const fn = (col.fieldname || '').toLowerCase();
        return ft === 'currency' || ft === 'float' || ft === 'int' || ft === 'percent' ||
          fn.includes('total') || fn.includes('amount') || fn.includes('rate') || fn.includes('price') || fn.includes('qty');
      };

      // Format cell value
      const formatCell = (val, col) => {
        if (val === null || val === undefined) return '<span style="color: var(--exrp-text-muted);">-</span>';
        if (isNumericCol(col) && typeof val === 'number') {
          const ft = (col.fieldtype || '').toLowerCase();
          if (ft === 'currency' || col.fieldname.toLowerCase().includes('total') || col.fieldname.toLowerCase().includes('amount')) {
            return Number(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
          }
          return Number(val).toLocaleString();
        }
        return escapeHtml(String(val));
      };

      // Extract or generate preview rows
      let previewRows = (validation && Array.isArray(validation.preview_data) && validation.preview_data.length > 0)
        ? validation.preview_data
        : ((reportDef && Array.isArray(reportDef.preview_data) && reportDef.preview_data.length > 0) ? reportDef.preview_data : []);

      if (previewRows.length === 0) {
        const prefix = targetDocType.replace(/[^A-Za-z]/g, '').substring(0, 3).toUpperCase() || 'DOC';
        previewRows = [
          { name: `${prefix}-2026-001`, customer: 'Acme Corporation', status: 'Pending', grand_total: 84500.00 },
          { name: `${prefix}-2026-002`, customer: 'Globex Logistics', status: 'Pending', grand_total: 62300.50 },
          { name: `${prefix}-2026-003`, customer: 'Stark Industries', status: 'Pending', grand_total: 45000.00 },
          { name: `${prefix}-2026-004`, customer: 'Wayne Enterprises', status: 'Pending', grand_total: 38200.75 },
          { name: `${prefix}-2026-005`, customer: 'Cyberdyne Systems', status: 'Pending', grand_total: 29800.00 },
        ];
      }

      // Column chips HTML
      const columnChipsHtml = normalizedColumns.map(col => `
        <span class="exrp-col-chip" title="Field: ${escapeHtml(col.fieldname)} (${escapeHtml(col.fieldtype || 'Data')})">
          <code>[${escapeHtml(col.fieldname)}]</code>
          ${col.label && col.label !== col.fieldname ? `<span class="exrp-col-label">${escapeHtml(col.label)}</span>` : ''}
        </span>
      `).join('');

      // Filter badges HTML
      const filterPillsHtml = filters.length > 0
        ? filters.map(f => {
            const fn = f.fieldname || 'field';
            const op = f.operator || '=';
            const val = f.value !== undefined ? (typeof f.value === 'object' ? JSON.stringify(f.value) : String(f.value)) : '';
            return `
              <span class="exrp-filter-pill" title="Filter: ${escapeHtml(fn)} ${escapeHtml(op)} ${escapeHtml(val)}">
                <span class="exrp-filter-fn">${escapeHtml(fn)}</span>
                <span class="exrp-filter-op">${escapeHtml(op)}</span>
                <span class="exrp-filter-val">'${escapeHtml(val)}'</span>
              </span>
            `;
          }).join('')
        : '<span style="font-size: 11px; color: var(--exrp-text-muted);">No query filters (Matches all records)</span>';

      // Chart Info HTML
      let chartInfoHtml = '';
      if (chart) {
        const cType = chart.chart_type || 'Bar';
        const xField = chart.x_field || 'x';
        const yFields = Array.isArray(chart.y_fields) ? chart.y_fields.join(', ') : (chart.y_fields || 'y');
        chartInfoHtml = `
          <span class="exrp-chart-pill" title="Chart Visualization">
            <span>📊 ${escapeHtml(cType)} Chart:</span>
            <strong>${escapeHtml(xField)}</strong> vs <strong>${escapeHtml(yFields)}</strong>
          </span>
        `;
      }

      // Safety Gate Badge
      const safetyBadgeHtml = isValid
        ? `<div class="exrp-report-safety-badge verified">
             <span class="exrp-safety-icon">✓</span>
             <span>REPORT SPECIFICATION VERIFIED - ZERO DDL IMPACT</span>
           </div>`
        : `<div class="exrp-report-safety-badge rejected">
             <span class="exrp-safety-icon">✕</span>
             <span>REJECTED: ${escapeHtml(errorMessage)}</span>
           </div>`;

      // Build card HTML
      const cardWrapper = document.createElement('div');
      cardWrapper.className = 'exrp-msg-row exrp-msg-assistant';
      cardWrapper.innerHTML = `
        <div class="exrp-msg-avatar">✨</div>
        <div class="exrp-msg-body">
          <div class="exrp-report-card" id="${cardId}">
            <!-- Card Header -->
            <div class="exrp-card-header">
              <div class="exrp-card-title-group">
                <span class="exrp-card-title">${escapeHtml(reportName)}</span>
                <span class="exrp-intent-badge">${escapeHtml(proposal.intent || 'create_report')}</span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                <span class="exrp-doctype-badge">${escapeHtml(targetDocType)}</span>
                <div id="${cardId}-header-badge">
                  <span class="exrp-report-status-badge draft">Draft Preview</span>
                </div>
              </div>
            </div>

            <!-- Card Body -->
            <div class="exrp-card-body">
              <!-- Summary & Rationale -->
              <div class="exrp-proposal-summary">
                ${escapeHtml(proposal.summary || data.error_message || 'AI Proposed Declarative Report Builder Specification')}
              </div>
              ${
                proposal.reasoning
                  ? `<div class="exrp-proposal-rationale">
                      <div class="exrp-rationale-label">Design Rationale</div>
                      <div>${escapeHtml(proposal.reasoning)}</div>
                    </div>`
                  : ''
              }

              <!-- Safety Verification Badge -->
              ${safetyBadgeHtml}

              <!-- Report Metadata Details -->
              <div class="exrp-report-meta">
                <!-- Columns Section -->
                <div class="exrp-report-meta-section">
                  <div class="exrp-section-label">
                    <span>Columns</span>
                    <span style="font-size: 10px; font-weight: normal; color: var(--exrp-text-muted);">${normalizedColumns.length} fields</span>
                  </div>
                  <div class="exrp-report-meta-row">
                    ${columnChipsHtml}
                  </div>
                </div>

                <!-- Filters Section -->
                <div class="exrp-report-meta-section">
                  <div class="exrp-section-label">
                    <span>Filters</span>
                    <span style="font-size: 10px; font-weight: normal; color: var(--exrp-text-muted);">${filters.length} rules</span>
                  </div>
                  <div class="exrp-report-meta-row">
                    ${filterPillsHtml}
                  </div>
                </div>

                <!-- Sorting & Chart Section -->
                <div class="exrp-report-meta-section">
                  <div class="exrp-report-meta-row">
                    <span class="exrp-sort-pill">
                      <span>↕ Sort:</span>
                      <strong>${escapeHtml(sortBy)}</strong> (${escapeHtml(sortOrder)})
                    </span>
                    ${chartInfoHtml}
                    ${reportDef.add_total_row ? `<span class="exrp-sort-pill" style="color: var(--exrp-success);">∑ Total Row</span>` : ''}
                  </div>
                </div>
              </div>

              <!-- Virtual Data Preview Table -->
              <div class="exrp-report-preview-container">
                <div class="exrp-preview-table-header">
                  <div class="exrp-virtual-badge">
                    <span class="exrp-pulse-dot" style="background: #0284c7; box-shadow: 0 0 0 rgba(2, 132, 199, 0.7);"></span>
                    <span>[VIRTUAL DATA PREVIEW - 0 DB DDL]</span>
                  </div>
                  <span class="exrp-preview-count">${previewRows.length} sample rows</span>
                </div>
                <div class="exrp-table-scroll-wrapper">
                  <table class="exrp-report-table">
                    <thead>
                      <tr>
                        ${normalizedColumns.map(col => `
                          <th class="${isNumericCol(col) ? 'numeric' : ''}" title="${escapeHtml(col.fieldname)}">
                            ${escapeHtml(col.label)}
                          </th>
                        `).join('')}
                      </tr>
                    </thead>
                    <tbody>
                      ${previewRows.slice(0, 5).map(row => `
                        <tr>
                          ${normalizedColumns.map(col => `
                            <td class="${isNumericCol(col) ? 'numeric' : ''}" title="${escapeHtml(String(row[col.fieldname] !== undefined ? row[col.fieldname] : ''))}">
                              ${formatCell(row[col.fieldname], col)}
                            </td>
                          `).join('')}
                        </tr>
                      `).join('')}
                    </tbody>
                  </table>
                </div>
              </div>

              <!-- Preview Fidelity Notice -->
              <div class="exrp-fidelity-notice">
                <span class="exrp-fidelity-icon">ℹ️</span>
                <span>${escapeHtml(data.preview_fidelity_notice || 'Interactive Virtual Data Table previewed with zero DB DDL schema mutations. Report runs against native Frappe Report Builder upon deployment.')}</span>
              </div>
            </div>

            <!-- Card Actions -->
            <div class="exrp-card-footer" id="${cardId}-footer">
              ${
                isValid
                  ? `<div class="exrp-card-actions">
                      <button type="button" class="exrp-btn-action exrp-btn-dismiss" id="${cardId}-btn-dismiss">Dismiss</button>
                      <button type="button" class="exrp-btn-action exrp-btn-deploy" id="${cardId}-btn-deploy">🚀 Deploy Report to Desk</button>
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
          this.executeReportDeployment(cardId, targetDocType, proposal, reportDef, validation);
        });
      }
    }

    /**
     * Executes Animated 3-Stage Report Builder Deployment (PRD-001, ADR-001 §10, ADR-006)
     * 1. Validate Columns & Filter Operators
     * 2. Acquire Advisory Lock
     * 3. Register Report Builder Metadata
     */
    executeReportDeployment(cardId, doctype, proposal, reportDef, validation) {
      const footerEl = document.getElementById(`${cardId}-footer`);
      if (!footerEl) return;

      this.isDeploying = true;
      this.sendBtnEl.disabled = true;

      // Render 3-stage report deployment tracker HTML
      footerEl.innerHTML = `
        <div class="exrp-deployment-tracker" id="${cardId}-rep-tracker">
          <div class="exrp-tracker-title">
            <span>📊 Declarative Report Deployment Sequence</span>
          </div>
          <div class="exrp-stage-list">
            <div class="exrp-stage-item in-progress" id="${cardId}-stage-1">
              <span class="exrp-stage-icon">⚙️</span>
              <span class="exrp-stage-name">1. Validate Columns &amp; Filter Operators</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-2">
              <span class="exrp-stage-icon">2</span>
              <span class="exrp-stage-name">2. Acquire Advisory Lock</span>
            </div>
            <div class="exrp-stage-item pending" id="${cardId}-stage-3">
              <span class="exrp-stage-icon">3</span>
              <span class="exrp-stage-name">3. Register Report Builder Metadata</span>
            </div>
          </div>
          <div id="${cardId}-tracker-result"></div>
        </div>
      `;

      const stage1 = footerEl.querySelector(`#${cardId}-stage-1`);
      const stage2 = footerEl.querySelector(`#${cardId}-stage-2`);
      const stage3 = footerEl.querySelector(`#${cardId}-stage-3`);
      const resultBox = footerEl.querySelector(`#${cardId}-tracker-result`);

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

      // Progress through initial verification stages
      setTimeout(() => advanceStage(stage1, stage2), 350);
      setTimeout(() => advanceStage(stage2, stage3), 750);

      const targetDocType = (window.cur_frm && window.cur_frm.doctype) ? window.cur_frm.doctype : (reportDef.ref_doctype || proposal.target_doctype || doctype);
      const deploymentId = (proposal && proposal.deployment_id) || ('dep_rep_' + Math.random().toString(36).substring(2, 10));
      const deployedReportPayload = proposal.report || reportDef;
      if (!deployedReportPayload.ref_doctype) {
        deployedReportPayload.ref_doctype = targetDocType;
      }
      const reportName = deployedReportPayload.report_name || reportDef.report_name || `${targetDocType} High-Value Pending Report`;
      if (!deployedReportPayload.report_name) {
        deployedReportPayload.report_name = reportName;
      }

      const handleDeploySuccess = (res) => {
        advanceStage(stage3, null);

        setTimeout(() => {
          this.isDeploying = false;
          if (this.sendBtnEl) {
            this.sendBtnEl.disabled = !(this.inputEl && this.inputEl.value && this.inputEl.value.trim());
          }

          const activeDepId = (res && res.deployment_id) || deploymentId;
          const activeRepName = (res && res.report_name) || reportName;
          const reportUrl = (res && res.report_url) || `/app/query-report/${encodeURIComponent(activeRepName)}`;

          // Update header status badge to [REPORT DEPLOYED]
          const headerBadge = document.getElementById(`${cardId}-header-badge`);
          if (headerBadge) {
            headerBadge.innerHTML = `<span class="exrp-report-status-badge deployed"><span class="exrp-pulse-dot"></span> REPORT DEPLOYED</span>`;
          }

          resultBox.innerHTML = `
            <div class="exrp-deploy-success-box">
              <div class="exrp-deploy-success-details">
                <div class="exrp-deploy-success-msg">
                  <span class="exrp-report-status-badge deployed"><span class="exrp-pulse-dot"></span> REPORT DEPLOYED</span>
                  <span>✓ Report <code>${escapeHtml(activeRepName)}</code> is now deployed to Frappe Desk!</span>
                </div>
                <div class="exrp-report-action-buttons">
                  <button type="button" class="exrp-btn-action exrp-btn-open-report" id="${cardId}-btn-open-report" title="Open Report in Desk">
                    🚀 Open Report in Desk
                  </button>
                  <button type="button" class="exrp-btn-action exrp-btn-revert" id="${cardId}-btn-revert" title="Deactivate or restore previous baseline safely" data-deployment-id="${escapeHtml(activeDepId)}">
                    ↩️ Deactivate / Revert Report
                  </button>
                </div>
              </div>
            </div>
          `;

          // Bind Open Report in Desk button
          const openReportBtn = resultBox.querySelector(`#${cardId}-btn-open-report`);
          if (openReportBtn) {
            openReportBtn.addEventListener('click', () => {
              if (window.frappe && typeof window.frappe.set_route === 'function') {
                window.frappe.set_route('query-report', activeRepName);
              } else {
                window.open(reportUrl, '_blank');
              }
            });
          }

          // Bind 1-Click Report Rollback UI
          const revertBtn = resultBox.querySelector(`#${cardId}-btn-revert`);
          if (revertBtn) {
            revertBtn.addEventListener('click', () => {
              const confirmMessage = "Are you sure you want to deactivate this report? This will soft-disable the report (disabled=1) or restore the previous baseline without touching underlying document data.";

              const executeRevert = () => {
                revertBtn.disabled = true;
                revertBtn.innerHTML = '⏳ Deactivating Report...';

                const onRevertSuccess = (revertResult) => {
                  revertBtn.innerHTML = '✓ Report Deactivated';
                  revertBtn.classList.add('exrp-reverted');
                  revertBtn.disabled = true;

                  if (headerBadge) {
                    headerBadge.innerHTML = `<span class="exrp-report-status-badge deactivated">REPORT DISABLED</span>`;
                  }

                  const activeBadges = resultBox.querySelectorAll('.exrp-report-status-badge.deployed');
                  activeBadges.forEach((b) => {
                    b.className = 'exrp-report-status-badge deactivated';
                    b.innerHTML = 'REPORT DISABLED';
                  });

                  // 1. Triggers cur_frm.reload_doc() if on doc form
                  if (window.cur_frm && window.cur_frm.doctype === targetDocType && typeof window.cur_frm.reload_doc === 'function') {
                    window.cur_frm.reload_doc();
                  }

                  // 2. Updates context count
                  this.updateContext();

                  // 3. Alerts user
                  if (window.frappe && typeof window.frappe.show_alert === 'function') {
                    window.frappe.show_alert({
                      message: __('EXRP: Report safely deactivated / baseline restored.'),
                      indicator: 'orange',
                    });
                  }

                  this.appendAssistantMessage(
                    `↩️ <strong>Report Deactivated:</strong> Report <code>${escapeHtml(activeRepName)}</code> on <strong>${escapeHtml(targetDocType)}</strong> has been soft-disabled (disabled=1) and baseline restored without touching records.`
                  );
                };

                const onRevertFailure = (err) => {
                  revertBtn.disabled = false;
                  revertBtn.innerHTML = '↩️ Deactivate / Revert Report';
                  const msg = (err && (err.message || err.reason)) || 'Failed to revert report builder metadata.';
                  if (window.frappe && typeof window.frappe.msgprint === 'function') {
                    window.frappe.msgprint({
                      title: __('Report Rollback Blocked'),
                      message: __(msg),
                      indicator: 'red',
                    });
                  } else {
                    alert(`Report Rollback Failed: ${msg}`);
                  }
                };

                // RPC call to revert_configuration_change
                if (window.frappe && typeof window.frappe.call === 'function') {
                  window.frappe.call({
                    method: 'exrp.api.control_plane.revert_configuration_change',
                    args: {
                      deployment_id: activeDepId,
                    },
                    callback: (r) => {
                      const outcome = r ? r.message : null;
                      if (outcome && (outcome.status === 'ROLLED_BACK' || outcome.disposition === 'REPORT_DISABLED' || outcome.disposition === 'PREVIOUS_REPORT_RESTORED' || outcome.success !== false)) {
                        onRevertSuccess(outcome);
                      } else {
                        onRevertFailure(outcome || { message: 'Report rollback rejected by control plane' });
                      }
                    },
                    error: (e) => onRevertFailure(e),
                  });
                } else {
                  // Mock rollback fallback
                  setTimeout(() => {
                    onRevertSuccess({ status: 'ROLLED_BACK', disposition: 'REPORT_DISABLED', success: true });
                  }, 500);
                }
              };

              // Native Frappe confirmation dialog
              if (window.frappe && typeof window.frappe.confirm === 'function') {
                window.frappe.confirm(confirmMessage, executeRevert);
              } else if (window.confirm(confirmMessage)) {
                executeRevert();
              }
            });
          }

          // Show Frappe native alert
          if (window.frappe && typeof window.frappe.show_alert === 'function') {
            window.frappe.show_alert({
              message: __('EXRP: Report {0} deployed successfully to Desk!', [activeRepName]),
              indicator: 'green',
            });
          }

          // Update context
          this.updateContext();
          this.appendAssistantMessage(
            `🎉 <strong>Report Deployed!</strong> Report <code>${escapeHtml(activeRepName)}</code> is now active on <strong>${escapeHtml(targetDocType)}</strong>.`
          );
        }, 400);
      };

      const handleDeployFailure = (errReason) => {
        stage3.className = 'exrp-stage-item failed';
        stage3.querySelector('.exrp-stage-icon').textContent = '✕';
        this.isDeploying = false;
        if (this.sendBtnEl) {
          this.sendBtnEl.disabled = !(this.inputEl && this.inputEl.value && this.inputEl.value.trim());
        }

        resultBox.innerHTML = `
          <div style="margin-top: 8px; padding: 8px 12px; background: var(--exrp-danger-light); border: 1px solid var(--exrp-danger-border); border-radius: var(--exrp-radius-md); font-size: 11.5px; color: var(--exrp-danger); font-weight: 600;">
            ✕ Report Deployment Blocked: ${escapeHtml(errReason || 'Report validation failed')}
          </div>
        `;

        if (window.frappe && typeof window.frappe.msgprint === 'function') {
          window.frappe.msgprint({
            title: __('Report Deployment Blocked'),
            message: __(errReason || 'Safe report deployment gate blocked the operation.'),
            indicator: 'red',
          });
        }
      };

      // Backend call to apply_report_change
      if (window.frappe && typeof window.frappe.call === 'function') {
        window.frappe.call({
          method: 'exrp.api.control_plane.apply_report_change',
          args: {
            doctype: (window.cur_frm && window.cur_frm.doctype) ? window.cur_frm.doctype : targetDocType,
            deployment_id: deploymentId,
            report_def: deployedReportPayload,
          },
          callback: (r) => {
            const resp = r ? r.message : null;
            if (resp && (resp.status === 'APPLIED' || resp.success !== false)) {
              handleDeploySuccess(resp);
            } else {
              handleDeployFailure(resp ? (resp.reason || resp.disposition) : 'Unknown report deployment error');
            }
          },
          error: (e) => {
            handleDeployFailure(e ? (e.message || e.toString()) : 'Network error during report deployment');
          },
        });
      } else {
        // Mock deployment success for standalone testing
        setTimeout(() => {
          handleDeploySuccess({
            status: 'APPLIED',
            disposition: 'REPORT_BUILDER_DEPLOYED',
            report_name: reportName,
            report_url: `/app/query-report/${encodeURIComponent(reportName)}`,
            doctype: targetDocType,
          });
        }, 1200);
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
      window.exrp.sidecar.injectPreview = (proposal) => window.exrp.sidecar.instance.injectInPlaceFormPreview(proposal);
      window.exrp.sidecar.clearPreview = () => window.exrp.sidecar.instance.clearInPlaceFormPreview();
      window.exrp.sidecar.renderWorkflowProposalCard = (proposal, validation, options) => window.exrp.sidecar.instance.renderWorkflowProposalCard(proposal, validation, options);
      window.exrp.sidecar.renderReportProposalCard = (proposal, validation, options) => window.exrp.sidecar.instance.renderReportProposalCard(proposal, validation, options);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();
