import 'package:flutter/material.dart';

import '../../models/admin_audit.dart';
import '../../models/ingest_entry.dart';
import '../../services/admin_service.dart';

// Read-only view of the server's audit log: who logged in, who approved or
// rejected what, and which actions failed.
class AdminAuditPage extends StatefulWidget {
  const AdminAuditPage({super.key, required this.service, this.onClose});

  final AdminService service;
  final VoidCallback? onClose;

  @override
  State<AdminAuditPage> createState() => _AdminAuditPageState();
}

class _AdminAuditPageState extends State<AdminAuditPage> {
  static const _filters = <String, String?>{
    'All': null,
    'Logins': 'auth',
    'Paper decisions': 'admin.paper',
    'Feedback reviews': 'admin.feedback',
    'User changes': 'admin.user',
    'Graph runs': 'graph',
    'Errors': 'system',
  };

  List<AuditEvent> _events = const [];
  String _filter = 'All';
  bool _failuresOnly = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final events = await widget.service.fetchAudit(
        type: _filters[_filter],
        outcome: _failuresOnly ? 'failure' : null,
      );
      if (!mounted) return;
      setState(() {
        _events = events;
        _loading = false;
      });
    } on AdminException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Audit log'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: widget.onClose,
        ),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<String>(
                    initialValue: _filter,
                    decoration: const InputDecoration(labelText: 'Show'),
                    items: [
                      for (final name in _filters.keys)
                        DropdownMenuItem(value: name, child: Text(name)),
                    ],
                    onChanged: (value) {
                      if (value == null) return;
                      _filter = value;
                      _refresh();
                    },
                  ),
                ),
                const SizedBox(width: 12),
                FilterChip(
                  label: const Text('Failures only'),
                  selected: _failuresOnly,
                  onSelected: (value) {
                    _failuresOnly = value;
                    _refresh();
                  },
                ),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(_error!, textAlign: TextAlign.center),
                    ),
                  )
                : _events.isEmpty
                ? const Center(child: Text('No events recorded yet.'))
                : ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: _events.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) =>
                        AuditEventTile(event: _events[index]),
                  ),
          ),
        ],
      ),
    );
  }
}

// Shared by the audit page and the dashboard's recent-errors list.
class AuditEventTile extends StatelessWidget {
  const AuditEventTile({super.key, required this.event});

  final AuditEvent event;

  @override
  Widget build(BuildContext context) {
    final detail = event.details.entries
        .map((entry) => '${entry.key}: ${entry.value}')
        .join('  ·  ');
    return ListTile(
      dense: true,
      leading: Icon(
        event.failed ? Icons.error_outline : Icons.check_circle_outline,
        color: event.failed ? Colors.red.shade700 : Colors.green.shade700,
      ),
      title: Text(
        '${event.type}  —  ${event.actor.isEmpty ? 'system' : event.actor}',
      ),
      subtitle: Text(
        [event.at, if (detail.isNotEmpty) detail].join('\n'),
        maxLines: 4,
        overflow: TextOverflow.ellipsis,
      ),
      isThreeLine: detail.isNotEmpty,
    );
  }
}
