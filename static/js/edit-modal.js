// ── Global Edit Modal ─────────────────────────────
// Standalone edit modal usable on any page.
// Requires: edit_modal.html partial in base.html
// API: PUT /api/devices/{table}/{id}
// ──────────────────────────────────────────────────

window.GlobalEditModal = (function () {

  let _tableName = null;
  let _deviceId  = null;
  let _basePath  = window.__BASE_PATH__ || '';
  let _onSuccess = null;

  // ── Status options by category ──────────────────
  const STATUS_OPTIONS = {
    edge_boxes: [
      'Production','QA Lab','Customer Lab','Demo Kit',
      'Hardware Lab','Company Inventory','Stock','Incomplete',
      'In Packaging','Out Of Box','Product Support Office',
      'Retired'
    ],
    nucs: [
      'Company Lab','Company Inventory','Customer Lab',
      'In Use','Retired'
    ],
    gpus: ['Available','In Use','Faulty','Retired'],
    hard_drives: [
      'Available','In Use (Testing)','In Device (LLM Machine)',
      'In Device','Faulty','Retired'
    ],
    cameras: ['Active','Inactive','Testing','Retired'],
    computers: ['Active','Inactive','Testing','Retired'],
    default: [
      'Active','Inactive','In Use','Available',
      'Testing','Retired','Decommissioned'
    ],
  };

  function _getStatusOptions(tableName) {
    return STATUS_OPTIONS[tableName] || STATUS_OPTIONS.default;
  }

  // ── Field definitions per category ──────────────
  // Each entry: { key, label, type, options?, required? }
  // type: 'text' | 'select' | 'textarea' | 'number' | 'date' | 'checkbox'

  const COMMON_FIELDS = [
    { key: 'serial',       label: 'Serial Number', type: 'text' },
    { key: 'manufacturer', label: 'Manufacturer',  type: 'text' },
    { key: 'model',        label: 'Model',         type: 'text' },
    { key: 'location',     label: 'Location',      type: 'text' },
    { key: 'status',       label: 'Status',        type: 'select',
      options: [] }, // populated dynamically
    { key: 'mac_address',  label: 'MAC Address',   type: 'text' },
    { key: 'mac_address_2', label: 'MAC Address 2', type: 'text', colRight: true },
    { key: 'ip_address',   label: 'IP Address',    type: 'text' },
  ];

  const CATEGORY_FIELDS = {
    edge_boxes: [
      { key: 'part_number',     label: 'Part Number',    type: 'text' },
      { key: 'form_factor',     label: 'Form Factor',    type: 'select',
        options: ['SFF','MFF','1U','2U','NUC','Desktop'] },
      { key: 'deployment_type', label: 'Deployment Type', type: 'select',
        options: ['customer','pilot','demo','trade_show','internal','stock'] },
      { key: 'org',             label: 'Org',            type: 'text' },
      { key: 'customer',        label: 'Customer',       type: 'text' },
      { key: 'partner',         label: 'Partner',        type: 'text' },
      { key: 'site_name',       label: 'Site Name',      type: 'text' },
      { key: 'warranty_id',     label: 'Warranty ID',    type: 'text' },
      { key: 'uuid',            label: 'UUID',           type: 'text' },
      { key: 'incomplete_reason', label: 'Incomplete Reason', type: 'textarea' },
    ],
    nucs: [
      { key: 'deployment_type', label: 'Deployment Type', type: 'select',
        options: ['internal','customer','pilot','demo','trade_show','stock'] },
      { key: 'uuid',    label: 'UUID',    type: 'text' },
      { key: 'purpose', label: 'Purpose', type: 'text' },
      { key: 'org',     label: 'Org',     type: 'text' },
    ],
    computers: [
      { key: 'device',      label: 'Device Brand',  type: 'text' },
      { key: 'device_name', label: 'Device Name',   type: 'text' },
      { key: 'assigned_to', label: 'Assigned To',   type: 'text' },
      { key: 'purpose',     label: 'Purpose',       type: 'text' },
      { key: 'os',          label: 'OS',            type: 'text' },
      { key: 'os_version',  label: 'OS Version',    type: 'text' },
      { key: 'primary_user_upn', label: 'Primary User UPN', type: 'text' },
    ],
    gpus: [
      { key: 'gpu_serial',            label: 'GPU Serial',
        type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    hard_drives: [
      { key: 'drive_type',   label: 'Drive Type',   type: 'select',
        options: ['HDD','SSD','NVMe M.2 SSD','NAS','Other'] },
      { key: 'capacity_tb',  label: 'Capacity (TB)', type: 'number' },
      { key: 'capacity_gb',  label: 'Capacity (GB)', type: 'number' },
      { key: 'interface',    label: 'Interface',    type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    cameras: [
      { key: 'deployment_type', label: 'Deployment Type', type: 'select',
        options: ['internal','customer','pilot','demo','trade_show','stock'] },
      { key: 'device_name', label: 'Device Name', type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
      { key: 'purpose',     label: 'Purpose',     type: 'text' },
    ],
    ram_modules: [
      { key: 'ram_type',   label: 'RAM Type',      type: 'text' },
      { key: 'capacity_gb', label: 'Capacity (GB)', type: 'number' },
      { key: 'speed_mhz',  label: 'Speed (MHz)',   type: 'number' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    cpus: [
      { key: 'socket', label: 'Socket', type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    psus: [
      { key: 'wattage_rating', label: 'Wattage Rating', type: 'text' },
      { key: 'efficiency',     label: 'Efficiency',     type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    motherboards: [
      { key: 'socket', label: 'Socket', type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    monitors: [
      { key: 'device',      label: 'Device',      type: 'text' },
      { key: 'model_code',  label: 'Model Code',  type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
      { key: 'purpose',     label: 'Purpose',     type: 'text' },
    ],
    phones: [
      { key: 'device',      label: 'Device',      type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
      { key: 'purpose',     label: 'Purpose',     type: 'text' },
    ],
    mobile_devices: [
      { key: 'device',        label: 'Device',        type: 'text' },
      { key: 'model_name',    label: 'Model Name',    type: 'text' },
      { key: 'model_number',  label: 'Model Number',  type: 'text' },
      { key: 'assigned_to',   label: 'Assigned To',   type: 'text' },
      { key: 'purpose',       label: 'Purpose',       type: 'text' },
    ],
    webcams: [
      { key: 'device',      label: 'Device',      type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
    ],
    printers: [
      { key: 'device',      label: 'Device',      type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
      { key: 'purpose',     label: 'Purpose',     type: 'text' },
    ],
    office_equipment: [
      { key: 'device',        label: 'Device',        type: 'text' },
      { key: 'model_name',    label: 'Model Name',    type: 'text' },
      { key: 'model_number',  label: 'Model Number',  type: 'text' },
      { key: 'assigned_to',   label: 'Assigned To',   type: 'text' },
      { key: 'purpose',       label: 'Purpose',       type: 'text' },
    ],
    network_equipment: [
      { key: 'device',      label: 'Device',      type: 'text' },
      { key: 'model_name',  label: 'Model Name',  type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
      { key: 'purpose',     label: 'Purpose',     type: 'text' },
    ],
    access_control: [
      { key: 'deployment_type', label: 'Deployment Type', type: 'select',
        options: ['internal','customer','pilot','demo','trade_show','stock'] },
      { key: 'device_name', label: 'Device Name', type: 'text' },
      { key: 'assigned_to', label: 'Assigned To', type: 'text' },
      { key: 'purpose',     label: 'Purpose',     type: 'text' },
    ],
    ups: [
      { key: 'va_rating',  label: 'VA Rating',  type: 'text' },
      { key: 'wattage',    label: 'Wattage',    type: 'text' },
    ],
    pc_cooling: [
      { key: 'cooling_type', label: 'Cooling Type', type: 'text' },
      { key: 'speed_rpm',    label: 'Speed (RPM)',   type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    pc_accessories: [
      { key: 'accessory_type', label: 'Accessory Type', type: 'text' },
      { key: 'associated_device_serial', label: 'Associated Device',
        type: 'text' },
    ],
    nas_devices: [
      { key: 'bay_count',    label: 'Bay Count',  type: 'number' },
      { key: 'ram_gb',       label: 'RAM (GB)',   type: 'text' },
      { key: 'mac_address_1', label: 'MAC Address 1', type: 'text' },
      { key: 'mac_address_2', label: 'MAC Address 2', type: 'text' },
    ],
    part_numbers: [
      { key: 'vendor',       label: 'Vendor',       type: 'text' },
      { key: 'form_factor',  label: 'Form Factor',  type: 'text' },
      { key: 'service_type', label: 'Service Type', type: 'text' },
    ],
  };

  const PROCUREMENT_FIELDS = [
    { key: 'vendor',              label: 'Vendor',             type: 'text' },
    { key: 'purchase_date',       label: 'Purchase Date',      type: 'date' },
    { key: 'purchase_price',      label: 'Purchase Price',     type: 'text' },
    { key: 'procurement_method',  label: 'Procurement Method', type: 'text' },
    { key: 'purchase_order',      label: 'PO Number',          type: 'text' },
    { key: 'supplier_invoice',    label: 'Invoice Number',     type: 'text' },
  ];

  const REQUIRED_FIELDS = {
    edge_boxes:       ['serial','mac_address','part_number','status',
                       'deployment_type','location','form_factor'],
    nucs:             ['serial','status','location'],
    gpus:             ['gpu_serial','model','status'],
    cameras:          ['manufacturer','model','serial'],
    monitors:         ['device','serial','location'],
    computers:        ['device_name','serial','assigned_to'],
    phones:           ['device','serial','assigned_to'],
    mobile_devices:   ['device','serial','assigned_to'],
    webcams:          ['device','serial','assigned_to'],
    printers:         ['device','serial'],
    office_equipment: ['device','serial'],
    network_equipment:['device','serial'],
    access_control:   ['manufacturer','model','serial'],
    hard_drives:      ['manufacturer','model','drive_type',
                       'capacity_tb','status'],
    ram_modules:      ['manufacturer','ram_type','capacity_gb','status'],
    cpus:             ['manufacturer','model','status'],
    psus:             ['manufacturer','model','serial','status'],
    motherboards:     ['manufacturer','model','serial','status'],
    pc_cooling:       ['manufacturer','model','status'],
    pc_accessories:   ['manufacturer','model','serial','status'],
    ups:              ['manufacturer','model','serial','location'],
    part_numbers:     ['part_number','vendor'],
    nas_devices:      ['serial'],
  };

  // ── Build field HTML ─────────────────────────────
  function _buildField(field, value, tableName) {
    var required = (REQUIRED_FIELDS[tableName] || [])
      .includes(field.key);
    var reqMark  = required
      ? ' <span style="color:var(--sx-red)">*</span>' : '';
    var val      = value !== null && value !== undefined ? value : '';

    var input = '';
    if (field.type === 'select') {
      var opts = field.options && field.options.length
        ? field.options
        : _getStatusOptions(tableName);
      var optHtml = opts.map(function(o) {
        var label = o.replace(/_/g, ' ').replace(/\b\w/g, function(c){ return c.toUpperCase(); });
        return '<option value="' + o + '" ' + (val === o ? 'selected' : '') + '>' + label + '</option>';
      }).join('');
      input = '<select class="gem-input" name="' + field.key + '">' +
        '<option value="">— Select —</option>' +
        optHtml +
      '</select>';
    } else if (field.type === 'textarea') {
      input = '<textarea class="gem-input gem-textarea" name="' + field.key + '" rows="3">' + val + '</textarea>';
    } else if (field.type === 'checkbox') {
      input = '<label class="gem-checkbox">' +
        '<input type="checkbox" name="' + field.key + '" ' +
          (val ? 'checked' : '') + '> ' + field.label +
      '</label>';
      return '<div class="gem-field">' + input + '</div>';
    } else {
      var extraClass = field.key === 'uuid' ? ' gem-input--uuid' : '';
      input = '<input type="' + (field.type || 'text') + '" class="gem-input' + extraClass + '" name="' + field.key + '" value="' + String(val).replace(/"/g, '&quot;') + '">';
    }

    // Add copy button for UUID fields
    if (field.key === 'uuid' && val) {
      input = '<div class="gem-uuid-wrap">' + input +
        '<button type="button" class="gem-copy-btn" title="Copy UUID" onclick="navigator.clipboard.writeText(this.previousElementSibling.value).then(function(){var b=event.target.closest(\'.gem-copy-btn\');b.textContent=\'Copied!\';setTimeout(function(){b.textContent=\'Copy\';},1200);})">' +
        'Copy</button></div>';
    }

    var fullWidth = (field.key === 'uuid') ? ' gem-field--full' : '';
    var colClass = field.colRight ? ' gem-field--col2' : '';
    return '<div class="gem-field' + fullWidth + colClass + '">' +
      '<label class="gem-label">' + field.label + reqMark + '</label>' +
      input +
    '</div>';
  }

  // ── Render modal content ─────────────────────────
  function _render(device, tableName) {
    var catFields  = CATEGORY_FIELDS[tableName] || [];
    var statusOpts = _getStatusOptions(tableName);

    // Build common fields HTML
    var commonHtml = '';
    for (var i = 0; i < COMMON_FIELDS.length; i++) {
      var f = COMMON_FIELDS[i];
      if (f.key === 'status') {
        f.options = statusOpts;
      }
      // Skip serial for part_numbers (uses part_number instead)
      if (f.key === 'serial' && tableName === 'part_numbers') continue;
      // Skip manufacturer/model/mac/ip for GPUs (use category fields)
      if (tableName === 'gpus' &&
          ['manufacturer','model','mac_address','ip_address']
          .indexOf(f.key) !== -1) continue;
      var val = device[f.key];
      if (val !== undefined || ['serial','location','status']
          .indexOf(f.key) !== -1) {
        commonHtml += _buildField(f, val, tableName);
      }
    }

    // Build category fields HTML
    var catHtml = '';
    for (var j = 0; j < catFields.length; j++) {
      catHtml += _buildField(catFields[j], device[catFields[j].key], tableName);
    }

    // Build procurement HTML
    var procHtml = '';
    for (var k = 0; k < PROCUREMENT_FIELDS.length; k++) {
      procHtml += _buildField(PROCUREMENT_FIELDS[k], device[PROCUREMENT_FIELDS[k].key], tableName);
    }

    // Notes field
    var notesEl = document.querySelector('#gem-body textarea[name="notes"]');
    if (notesEl) notesEl.value = device.notes || '';

    // Category display name
    var catName = tableName.replace(/_/g, ' ')
      .replace(/\b\w/g, function(c) { return c.toUpperCase(); });

    document.getElementById('gem-category-badge').textContent = catName;
    document.getElementById('gem-title').textContent =
      device.serial || device.gpu_serial || device.device_name ||
      device.part_number || ('Device #' + device.id);

    document.getElementById('gem-common-fields').innerHTML  = commonHtml;
    document.getElementById('gem-category-fields').innerHTML = catHtml;
    document.getElementById('gem-procurement-fields').innerHTML = procHtml;
    document.getElementById('gem-error').style.display = 'none';
    document.getElementById('gem-success').style.display = 'none';
  }

  // ── Public: open ─────────────────────────────────
  function open(tableName, deviceId, options) {
    _tableName = tableName;
    _deviceId  = deviceId;
    _onSuccess = (options && options.onSuccess) || null;
    _basePath  = window.__BASE_PATH__ || '';

    var overlay = document.getElementById('gem-overlay');
    overlay.classList.add('open');
    document.getElementById('gem-loading').style.display = 'block';
    document.getElementById('gem-body').style.display = 'none';
    document.getElementById('gem-error').style.display = 'none';
    document.getElementById('gem-success').style.display = 'none';

    fetch(_basePath + '/api/devices/' + tableName + '/' + deviceId)
      .then(function(resp) {
        if (!resp.ok) throw new Error('Failed to load device');
        return resp.json();
      })
      .then(function(device) {
        _render(device, tableName);
        document.getElementById('gem-loading').style.display = 'none';
        document.getElementById('gem-body').style.display    = 'block';
      })
      .catch(function(err) {
        document.getElementById('gem-loading').style.display = 'none';
        var errDiv = document.getElementById('gem-error');
        errDiv.textContent = err.message || 'Failed to load device.';
        errDiv.style.display = 'block';
      });
  }

  // ── Public: save ─────────────────────────────────
  function save() {
    var saveBtn = document.getElementById('gem-save-btn');
    var errDiv  = document.getElementById('gem-error');
    var okDiv   = document.getElementById('gem-success');
    saveBtn.disabled = true;
    errDiv.style.display  = 'none';
    okDiv.style.display   = 'none';

    // Collect all named inputs
    var body = document.getElementById('gem-body');
    var inputs = body.querySelectorAll('[name]');
    var payload = {};
    inputs.forEach(function(el) {
      if (el.type === 'checkbox') {
        payload[el.name] = el.checked;
      } else {
        payload[el.name] = el.value || null;
      }
    });

    fetch(_basePath + '/api/devices/' + _tableName + '/' + _deviceId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function(resp) {
        return resp.json().then(function(data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function(result) {
        if (result.ok) {
          okDiv.textContent  = 'Saved successfully.';
          okDiv.style.display = 'block';
          if (_onSuccess) _onSuccess(result.data);
          setTimeout(function() { close(); }, 900);
        } else {
          errDiv.textContent = result.data.detail || 'Save failed.';
          errDiv.style.display = 'block';
        }
        saveBtn.disabled = false;
      })
      .catch(function() {
        errDiv.textContent = 'Network error. Please try again.';
        errDiv.style.display = 'block';
        saveBtn.disabled = false;
      });
  }

  // ── Public: close ────────────────────────────────
  function close() {
    document.getElementById('gem-overlay').classList.remove('open');
    _tableName = null;
    _deviceId  = null;
    _onSuccess = null;
    document.dispatchEvent(new Event('modal-closed'));
  }

  return { open: open, save: save, close: close };

})();

// Close on overlay click + set base path from meta tag
document.addEventListener('DOMContentLoaded', function () {
  var overlay = document.getElementById('gem-overlay');
  if (overlay) {
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) GlobalEditModal.close();
    });
  }
  var meta = document.querySelector('meta[name="base-path"]');
  if (meta) window.__BASE_PATH__ = meta.getAttribute('content');
});
