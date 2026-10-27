import 'package:flutter/material.dart';

import '../../models/admin_feedback.dart';
import '../../models/ingest_entry.dart';
import '../../services/admin_service.dart';

// Admin queue for user feedback: stats at the top, then each entry with the
// graph triples it was attached to. Accepting a complaint can archive those
// triples (reversible: they are flagged, not deleted, and drop out of answers).
class AdminFeedbackPage extends StatefulWidget {
  const AdminFeedbackPage({super.key, required this.service, this.onClose});

  final AdminService service;
  final VoidCallback? onClose;

  @override
  State<AdminFeedbackPage> createState() => _AdminFeedbackPageState();
}

class _AdminFeedbackPageState extends State<AdminFeedbackPage> {
  List<AdminFeedback> _items = const [];
  FeedbackStats _stats = const FeedbackStats();
  String _filter = 'pending';
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
      final results = await Future.wait([
        widget.service.fetchFeedback(status: _filter),
        widget.service.fetchFeedbackStats(),
      ]);
      if (!mounted) return;
      setState(() {
        _items = results[0] as List<AdminFeedback>;
        _stats = results[1] as FeedbackStats;
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

  Future<void> _review(AdminFeedback item) async {
    final result = await showDialog<_ReviewResult>(
      context: context,
      builder: (context) => _FeedbackReviewDialog(item: item),
    );
    if (result == null) return;
    try {
      await widget.service.reviewFeedback(
        item.id,
        action: result.action,
        note: result.note,
        archiveTripleIds: result.action == 'approved'
            ? result.archiveTripleIds
            : null,
        correction: result.correction,
      );
      await _refresh();
    } on AdminException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Feedback review'),
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
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(_error!, textAlign: TextAlign.center),
              ),
            )
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                _StatsCard(stats: _stats),
                const SizedBox(height: 16),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'pending', label: Text('Pending')),
                    ButtonSegment(value: 'reviewed', label: Text('Reviewed')),
                  ],
                  selected: {_filter},
                  onSelectionChanged: (value) {
                    _filter = value.first;
                    _refresh();
                  },
                ),
                const SizedBox(height: 16),
                if (_items.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: Text('Nothing here.')),
                  ),
                for (final item in _items)
                  _FeedbackTile(item: item, onReview: () => _review(item)),
              ],
            ),
    );
  }
}

class _StatsCard extends StatelessWidget {
  const _StatsCard({required this.stats});

  final FeedbackStats stats;

  @override
  Widget build(BuildContext context) {
    Widget cell(String label, int value) => Expanded(
      child: Column(
        children: [
          Text(
            '$value',
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
          ),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Row(
              children: [
                cell('Total', stats.total),
                cell('Helpful', stats.helpful),
                cell('Not helpful', stats.notHelpful),
              ],
            ),
            const Divider(height: 24),
            Row(
              children: [
                cell('Pending', stats.pending),
                cell('Accepted', stats.approved),
                cell('Dismissed', stats.dismissed),
                cell('Archived triples', stats.archivedTriples),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _FeedbackTile extends StatelessWidget {
  const _FeedbackTile({required this.item, required this.onReview});

  final AdminFeedback item;
  final VoidCallback onReview;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  item.isNotHelpful
                      ? Icons.thumb_down_outlined
                      : Icons.thumb_up_outlined,
                  size: 18,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    item.userEmail,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (!item.isReviewed)
                  FilledButton.tonal(
                    onPressed: onReview,
                    child: const Text('Review'),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              item.responseText,
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
            ),
            if (item.comment.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('“${item.comment}”'),
            ],
            if (item.triples.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'Triples shown',
                style: Theme.of(context).textTheme.labelMedium,
              ),
              for (final triple in item.triples)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    '${triple.archived ? '[archived] ' : ''}${triple.label}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
            ],
            if (item.isReviewed) ...[
              const SizedBox(height: 12),
              Text(
                '${item.reviewAction == 'approved' ? 'Accepted' : 'Dismissed'}'
                ' by ${item.reviewedBy} ${item.reviewedAt}'
                '${item.reviewNote.isEmpty ? '' : ' — ${item.reviewNote}'}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ReviewResult {
  const _ReviewResult(
    this.action,
    this.note,
    this.archiveTripleIds, [
    this.correction,
  ]);

  final String action;
  final String note;
  // The exact triples to archive. Empty means archive nothing.
  final List<String> archiveTripleIds;
  final TripleCorrection? correction;
}

class _FeedbackReviewDialog extends StatefulWidget {
  const _FeedbackReviewDialog({required this.item});

  final AdminFeedback item;

  @override
  State<_FeedbackReviewDialog> createState() => _FeedbackReviewDialogState();
}

class _FeedbackReviewDialogState extends State<_FeedbackReviewDialog> {
  final _note = TextEditingController();
  final _subject = TextEditingController();
  final _predicate = TextEditingController();
  final _object = TextEditingController();
  final Set<String> _archiveIds = {};
  FeedbackTriple? _correcting;

  @override
  void dispose() {
    _note.dispose();
    _subject.dispose();
    _predicate.dispose();
    _object.dispose();
    super.dispose();
  }

  void _startCorrection(FeedbackTriple? triple) {
    setState(() {
      _correcting = triple;
      _subject.text = triple?.subject ?? '';
      _predicate.text = triple?.predicate ?? '';
      _object.text = triple?.object ?? '';
    });
  }

  TripleCorrection? get _correction {
    final triple = _correcting;
    if (triple == null) return null;
    final subject = _subject.text.trim();
    final predicate = _predicate.text.trim();
    final object = _object.text.trim();
    if (subject.isEmpty || predicate.isEmpty || object.isEmpty) return null;
    return TripleCorrection(
      tripleId: triple.id,
      subject: subject,
      predicate: predicate,
      object: object,
    );
  }

  @override
  Widget build(BuildContext context) {
    final live = widget.item.triples.where((t) => !t.archived).toList();
    return AlertDialog(
      title: const Text('Review feedback'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _note,
              maxLength: 2000,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Note (optional)'),
            ),
            if (widget.item.triples.any((t) => !t.archived)) ...[
              const SizedBox(height: 8),
              DropdownButtonFormField<FeedbackTriple?>(
                initialValue: _correcting,
                decoration: const InputDecoration(
                  labelText: 'Correct a triple (optional)',
                ),
                items: [
                  const DropdownMenuItem(value: null, child: Text('None')),
                  for (final t in widget.item.triples.where((t) => !t.archived))
                    DropdownMenuItem(
                      value: t,
                      child: Text(t.label, overflow: TextOverflow.ellipsis),
                    ),
                ],
                onChanged: _startCorrection,
                isExpanded: true,
              ),
              if (_correcting != null) ...[
                TextField(
                  controller: _subject,
                  decoration: const InputDecoration(labelText: 'Subject'),
                ),
                TextField(
                  controller: _predicate,
                  decoration: const InputDecoration(
                    labelText: 'Predicate (LETTERS_AND_UNDERSCORES)',
                  ),
                ),
                TextField(
                  controller: _object,
                  decoration: const InputDecoration(labelText: 'Object'),
                ),
              ],
            ],
            if (live.isNotEmpty && _correcting == null) ...[
              const SizedBox(height: 12),
              Text(
                'Archive triples (optional)',
                style: Theme.of(context).textTheme.labelLarge,
              ),
              const Text(
                'Nothing is archived unless you tick it. Archived triples '
                'stop appearing in answers. They are flagged, not deleted.',
              ),
              Row(
                children: [
                  TextButton(
                    onPressed: () => setState(() {
                      _archiveIds
                        ..clear()
                        ..addAll(
                          live
                              .where((t) => !t.id.startsWith('csv:'))
                              .map((t) => t.id),
                        );
                    }),
                    child: const Text('Select all'),
                  ),
                  TextButton(
                    onPressed: () => setState(_archiveIds.clear),
                    child: const Text('Clear'),
                  ),
                ],
              ),
              for (final t in live)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  controlAffinity: ListTileControlAffinity.leading,
                  value: _archiveIds.contains(t.id),
                  onChanged: t.id.startsWith('csv:')
                      ? null
                      : (v) => setState(() {
                          if (v == true) {
                            _archiveIds.add(t.id);
                          } else {
                            _archiveIds.remove(t.id);
                          }
                        }),
                  title: Text(t.label),
                  subtitle: t.id.startsWith('csv:')
                      ? const Text(
                          'From the CSV file, so it cannot be archived.',
                        )
                      : null,
                ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(
            context,
            _ReviewResult('rejected', _note.text, const []),
          ),
          child: const Text('Dismiss'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(
            context,
            _ReviewResult(
              'approved',
              _note.text,
              _correction == null ? _archiveIds.toList() : const [],
              _correction,
            ),
          ),
          child: const Text('Accept'),
        ),
      ],
    );
  }
}
