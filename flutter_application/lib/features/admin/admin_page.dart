import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../models/ingest_entry.dart';
import '../../services/admin_service.dart';

// A PDF chosen by the admin. The picker is injected rather than imported here
// so this screen has no dependency on any file-picking package: tests supply a
// fake, and app.dart wires the real one.
class PickedPdf {
  const PickedPdf({required this.filename, required this.bytes});

  final String filename;
  final Uint8List bytes;
}

typedef PdfPicker = Future<PickedPdf?> Function();

/// Shows a PDF the app already holds. Injected for the same reason as the
/// picker: the real one uses web-only APIs, and this screen's tests must
/// not need them.
typedef PdfViewer = Future<void> Function(String filename, Uint8List bytes);

// Lets an admin submit a paper for confidence scoring and see what the server
// decided.
//
// The top level is the verdicts, not a list of every admission: what an admin
// needs to know is how many papers are waiting on them, not to scroll a
// history. Opening a verdict shows the papers in it.
//
// Nothing here starts extraction. At the measured 157 seconds per chunk a
// 22-page paper is over two hours, and the hosted container has no GPU or job
// queue, so a human runs the CLI. The Extract button is a placeholder and says
// so when pressed.
class AdminPage extends StatefulWidget {
  const AdminPage({
    super.key,
    required this.service,
    required this.pickPdf,
    this.viewPdf,
    this.onClose,
    this.pollInterval = const Duration(seconds: 5),
  });

  final AdminService service;
  final PdfPicker pickPdf;

  /// Null means this build cannot display a PDF, so the review screen
  /// hides "View paper" rather than offering a button that does nothing.
  final PdfViewer? viewPdf;

  final VoidCallback? onClose;

  /// How often to re-read the queue. Scoring takes minutes and finishes
  /// server-side, so without polling the admin has to reload the page to find
  /// out what happened. Null disables it, which tests use because a periodic
  /// timer never lets pumpAndSettle settle.
  final Duration? pollInterval;

  @override
  State<AdminPage> createState() => _AdminPageState();
}

class _AdminPageState extends State<AdminPage> {
  List<IngestEntry> _queue = const [];
  bool _isLoadingQueue = true;
  bool _isUploading = false;
  String? _error;
  String? _notice;
  IngestDecision? _openCategory;
  Timer? _poller;

  // Papers uploaded in this session that have not yet appeared in the queue.
  // Between the upload and the verdict a paper is in no category at all, so
  // without this the admin uploads and watches nothing change for minutes.
  final _awaitingVerdict = <String>{};

  @override
  void initState() {
    super.initState();
    _refreshQueue();
    final interval = widget.pollInterval;
    if (interval != null) {
      _poller = Timer.periodic(interval, (_) => _refreshQueue(quietly: true));
    }
  }

  @override
  void dispose() {
    _poller?.cancel();
    super.dispose();
  }

  /// `quietly` is for the polling path: it must not flash a spinner over the
  /// list every few seconds, nor replace what the admin is reading with an
  /// error if one poll happens to fail.
  Future<void> _refreshQueue({bool quietly = false}) async {
    if (!quietly) {
      setState(() {
        _isLoadingQueue = true;
        _error = null;
      });
    }
    try {
      final queue = await widget.service.fetchQueue();
      if (!mounted) return;
      setState(() {
        _queue = queue;
        _isLoadingQueue = false;
        _error = null;
        _awaitingVerdict.removeWhere(
          (paper) => queue.any((entry) => entry.paper == paper),
        );
      });
    } on AdminException catch (error) {
      if (!mounted) return;
      setState(() {
        _isLoadingQueue = false;
        if (!quietly) _error = error.message;
      });
    }
  }

  Future<void> _uploadPaper() async {
    final picked = await widget.pickPdf();
    if (picked == null) return; // the admin cancelled the file dialog

    setState(() {
      _isUploading = true;
      _error = null;
      _notice = null;
    });

    try {
      final ack = await widget.service.uploadPdf(
        bytes: picked.bytes,
        filename: picked.filename,
      );
      if (!mounted) return;
      setState(() {
        _isUploading = false;
        _notice = ack.message;
        // The server may have sanitised the name, so track what it returned.
        _awaitingVerdict.add(ack.paper);
      });
      await _refreshQueue(quietly: true);
    } on AdminException catch (error) {
      if (!mounted) return;
      setState(() {
        _isUploading = false;
        _error = error.message;
      });
    }
  }

  Future<void> _viewPaper(String paper) async {
    final viewer = widget.viewPdf;
    if (viewer == null) return;
    try {
      final bytes = await widget.service.fetchPaper(paper);
      await viewer(paper, bytes);
    } on AdminException catch (error) {
      if (!mounted) return;
      _say(error.message);
    }
  }

  /// Approve or reject a paper a person has actually read. The note is
  /// optional but asked for: a decision with no reason recorded is useless to
  /// whoever reads the queue afterwards, and the queue is the audit trail.
  Future<void> _review(IngestEntry entry, {required bool approve}) async {
    final note = await showDialog<String>(
      context: context,
      builder: (context) => _ReviewDialog(paper: entry.paper, approve: approve),
    );
    if (note == null) return; // cancelled

    try {
      await widget.service.submitReview(entry.paper, approve: approve, note: note);
      if (!mounted) return;
      setState(() => _openCategory = null);
      _say('${entry.paper} ${approve ? 'approved' : 'rejected'}.');
      await _refreshQueue(quietly: true);
    } on AdminException catch (error) {
      if (!mounted) return;
      _say(error.message);
    }
  }

  void _say(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 5)),
    );
  }

  void _notYetWired(String paper) {
    // Honest about being a placeholder. A button that looks real and silently
    // does nothing would have the admin believe extraction had started.
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 6),
        content: Text(
          'Extraction is not wired up yet. $paper is queued ready for it; '
          'run it from the CLI for now.',
        ),
      ),
    );
  }

  List<IngestEntry> _entriesIn(IngestDecision decision) =>
      _queue.where((entry) => entry.decision == decision).toList();

  @override
  Widget build(BuildContext context) {
    final open = _openCategory;

    return Scaffold(
      appBar: AppBar(
        title: Text(open == null
            ? 'Paper admission'
            : _categoryFor(open).label),
        leading: open != null
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                tooltip: 'Back to categories',
                onPressed: () => setState(() => _openCategory = null),
              )
            : widget.onClose == null
                ? null
                : IconButton(
                    icon: const Icon(Icons.arrow_back),
                    tooltip: 'Back to chat',
                    onPressed: widget.onClose,
                  ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh now',
            onPressed: _isLoadingQueue ? null : _refreshQueue,
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (open == null) _buildUploadSection(),
          if (open == null) const Divider(height: 24),
          Expanded(
            child: _isLoadingQueue
                ? const Center(child: CircularProgressIndicator())
                : open == null
                    ? _buildCategories()
                    : _buildCategoryDetail(open),
          ),
        ],
      ),
    );
  }

  Widget _buildUploadSection() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Upload a research paper to be scored against the confidence '
            'framework. Scoring takes a few minutes per paper; the verdict '
            'appears below on its own.',
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _isUploading ? null : _uploadPaper,
            icon: _isUploading
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.upload_file),
            label: Text(_isUploading ? 'Uploading…' : 'Choose a PDF'),
          ),
          if (_notice != null) ...[
            const SizedBox(height: 12),
            _Banner(text: _notice!, icon: Icons.schedule),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            _Banner(text: _error!, icon: Icons.error_outline, isError: true),
          ],
        ],
      ),
    );
  }

  Widget _buildCategories() {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      children: [
        for (final paper in _awaitingVerdict)
          Card(
            margin: const EdgeInsets.symmetric(vertical: 6),
            child: ListTile(
              leading: const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              title: Text(paper,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
              subtitle: const Text('Scoring — this takes a few minutes'),
            ),
          ),
        for (final decision in const [
          IngestDecision.readyToExtract,
          IngestDecision.heldForReview,
          IngestDecision.rejected,
          IngestDecision.scoringFailed,
        ])
          _CategoryCard(
            category: _categoryFor(decision),
            count: _entriesIn(decision).length,
            onTap: () => setState(() => _openCategory = decision),
          ),
      ],
    );
  }

  Widget _buildCategoryDetail(IngestDecision decision) {
    final entries = _entriesIn(decision);
    if (entries.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text('No papers are ${_categoryFor(decision).emptyPhrase}.'),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
      itemCount: entries.length,
      itemBuilder: (context, index) {
        final entry = entries[index];
        final underReview = decision == IngestDecision.heldForReview;
        return _PaperTile(
          entry: entry,
          category: _categoryFor(decision),
          onExtract: decision == IngestDecision.readyToExtract
              ? () => _notYetWired(entry.paper)
              : null,
          // Only where the file is still on the server to be read.
          onView: widget.viewPdf != null && entry.isStored
              ? () => _viewPaper(entry.paper)
              : null,
          onApprove: underReview ? () => _review(entry, approve: true) : null,
          onReject: underReview ? () => _review(entry, approve: false) : null,
        );
      },
    );
  }
}

// What each verdict is called, what it means, and how it looks. Keeping the
// wording here means the category card and its detail view cannot drift.
class _Category {
  const _Category({
    required this.label,
    required this.meaning,
    required this.emptyPhrase,
    required this.icon,
    required this.colour,
  });

  final String label;
  final String meaning;
  final String emptyPhrase;
  final IconData icon;
  final Color colour;
}

const _approvedColour = Color(0xFF2CB67D);
const _reviewColour = Color(0xFFB7791F);
const _rejectedColour = Color(0xFFC53030);
const _unscoredColour = Color(0xFF718096);

_Category _categoryFor(IngestDecision decision) {
  switch (decision) {
    case IngestDecision.readyToExtract:
      return const _Category(
        label: 'Approved',
        meaning: 'Scored above the threshold. Waiting for extraction.',
        emptyPhrase: 'waiting for extraction',
        icon: Icons.check_circle_outline,
        colour: _approvedColour,
      );
    case IngestDecision.heldForReview:
      return const _Category(
        label: 'Manual review',
        meaning: 'Scored in between. Needs a person to decide.',
        emptyPhrase: 'waiting for review',
        icon: Icons.pending_outlined,
        colour: _reviewColour,
      );
    case IngestDecision.rejected:
      return const _Category(
        label: 'Rejected',
        meaning: 'Scored below the threshold. The file was not kept.',
        emptyPhrase: 'rejected',
        icon: Icons.block,
        colour: _rejectedColour,
      );
    case IngestDecision.scoringFailed:
      return const _Category(
        label: "Scoring didn't run",
        meaning: 'Not a verdict — the confidence model could not be reached. '
            'These papers were kept and can be scored again.',
        emptyPhrase: 'waiting to be scored again',
        icon: Icons.cloud_off,
        colour: _unscoredColour,
      );
    case IngestDecision.unknown:
      return const _Category(
        label: 'Unknown',
        meaning: 'The server reported a decision this app does not recognise.',
        emptyPhrase: 'unrecognised',
        icon: Icons.help_outline,
        colour: _unscoredColour,
      );
  }
}

class _CategoryCard extends StatelessWidget {
  const _CategoryCard({
    required this.category,
    required this.count,
    required this.onTap,
  });

  final _Category category;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: ListTile(
        onTap: onTap,
        leading: Icon(category.icon, color: category.colour, size: 28),
        title: Text(category.label,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(category.meaning),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '$count',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: count == 0
                    ? Theme.of(context).colorScheme.outline
                    : category.colour,
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.chevron_right),
          ],
        ),
      ),
    );
  }
}

class _PaperTile extends StatelessWidget {
  const _PaperTile({
    required this.entry,
    required this.category,
    this.onExtract,
    this.onView,
    this.onApprove,
    this.onReject,
  });

  final IngestEntry entry;
  final _Category category;
  final VoidCallback? onExtract;
  final VoidCallback? onView;
  final VoidCallback? onApprove;
  final VoidCallback? onReject;

  @override
  Widget build(BuildContext context) {
    final small = Theme.of(context).textTheme.bodySmall;

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(category.icon, color: category.colour, size: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(entry.paper,
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                ),
                if (entry.isVerdict)
                  Text(entry.scoreLabel, style: small),
              ],
            ),
            if (!entry.isVerdict)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text(
                  'This is not a judgement on the paper. The confidence model '
                  'could not be reached, so the paper has been kept and can be '
                  'scored again.',
                  style: TextStyle(fontStyle: FontStyle.italic),
                ),
              ),
            for (final reason in entry.reasons)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('• $reason'),
              ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Text(
                    [
                      if (entry.at != null) 'Submitted ${entry.at}',
                      entry.isStored
                          ? 'Kept on the server'
                          : 'Not kept — the file was discarded',
                    ].join(' · '),
                    style: small,
                  ),
                ),
                if (onView != null)
                  TextButton.icon(
                    onPressed: onView,
                    icon: const Icon(Icons.picture_as_pdf_outlined, size: 18),
                    label: const Text('View paper'),
                  ),
                if (onReject != null) ...[
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: onReject,
                    child: const Text('Reject'),
                  ),
                ],
                if (onApprove != null) ...[
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: onApprove,
                    child: const Text('Approve'),
                  ),
                ],
                if (onExtract != null)
                  FilledButton.icon(
                    onPressed: onExtract,
                    icon: const Icon(Icons.play_arrow, size: 18),
                    label: const Text('Extract'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.text, required this.icon, this.isError = false});

  final String text;
  final IconData icon;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final colour = isError ? scheme.error : scheme.primary;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colour.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colour.withValues(alpha: 0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: colour),
          const SizedBox(width: 10),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}


// Asks for the reason behind a manual decision.
class _ReviewDialog extends StatefulWidget {
  const _ReviewDialog({required this.paper, required this.approve});

  final String paper;
  final bool approve;

  @override
  State<_ReviewDialog> createState() => _ReviewDialogState();
}

class _ReviewDialogState extends State<_ReviewDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final verb = widget.approve ? 'Approve' : 'Reject';
    return AlertDialog(
      title: Text('$verb ${widget.paper}?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(widget.approve
              ? 'It moves to Approved and is queued for extraction.'
              : 'It moves to Rejected. The file is kept, so this can be '
                  'revisited.'),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            autofocus: true,
            maxLines: 3,
            decoration: const InputDecoration(
              labelText: 'Why? (recorded in the queue)',
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controller.text.trim()),
          child: Text(verb),
        ),
      ],
    );
  }
}
