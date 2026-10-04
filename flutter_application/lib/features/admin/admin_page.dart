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

// Lets an admin submit a paper for confidence scoring and watch what the
// server decided.
//
// Scoring is an LLM job of minutes per paper, so an upload returns straight
// away and the verdict appears in the queue afterwards. Nothing here starts
// extraction: at the measured 157 seconds per chunk a 22-page paper is over
// two hours, so a human runs the CLI against the queue.
class AdminPage extends StatefulWidget {
  const AdminPage({
    super.key,
    required this.service,
    required this.pickPdf,
    this.onClose,
  });

  final AdminService service;
  final PdfPicker pickPdf;
  final VoidCallback? onClose;

  @override
  State<AdminPage> createState() => _AdminPageState();
}

class _AdminPageState extends State<AdminPage> {
  List<IngestEntry> _queue = const [];
  bool _isLoadingQueue = true;
  bool _isUploading = false;
  String? _error;
  String? _notice;

  @override
  void initState() {
    super.initState();
    _refreshQueue();
  }

  Future<void> _refreshQueue() async {
    setState(() {
      _isLoadingQueue = true;
      _error = null;
    });
    try {
      final queue = await widget.service.fetchQueue();
      if (!mounted) return;
      setState(() {
        _queue = queue;
        _isLoadingQueue = false;
      });
    } on AdminException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _isLoadingQueue = false;
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
      });
      await _refreshQueue();
    } on AdminException catch (error) {
      if (!mounted) return;
      setState(() {
        _isUploading = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Paper admission'),
        leading: widget.onClose == null
            ? null
            : IconButton(
                icon: const Icon(Icons.arrow_back),
                tooltip: 'Back to chat',
                onPressed: widget.onClose,
              ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh queue',
            onPressed: _isLoadingQueue ? null : _refreshQueue,
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Upload a research paper to be scored against the '
                  'confidence framework. Scoring takes a few minutes per '
                  'paper; the verdict appears below when it finishes.',
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
          ),
          const Divider(height: 24),
          Expanded(child: _buildQueue()),
        ],
      ),
    );
  }

  Widget _buildQueue() {
    if (_isLoadingQueue) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_queue.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('No papers have been submitted yet.'),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      itemCount: _queue.length,
      itemBuilder: (context, index) => _QueueTile(entry: _queue[index]),
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
        color: colour.withOpacity(0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colour.withOpacity(0.4)),
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

class _QueueTile extends StatelessWidget {
  const _QueueTile({required this.entry});

  final IngestEntry entry;

  // Scoring failures deliberately do not get a verdict colour: the paper was
  // not judged, the model was unreachable.
  ({String label, Color colour, IconData icon}) _presentation(ColorScheme scheme) {
    switch (entry.decision) {
      case IngestDecision.readyToExtract:
        return (label: 'Approved — ready to extract',
                colour: const Color(0xFF2CB67D), icon: Icons.check_circle_outline);
      case IngestDecision.heldForReview:
        return (label: 'Manual review', colour: const Color(0xFFB7791F),
                icon: Icons.pending_outlined);
      case IngestDecision.rejected:
        return (label: 'Rejected — not stored', colour: scheme.error,
                icon: Icons.block);
      case IngestDecision.scoringFailed:
        return (label: 'Scoring did not run', colour: scheme.outline,
                icon: Icons.cloud_off);
      case IngestDecision.unknown:
        return (label: 'Unknown', colour: scheme.outline, icon: Icons.help_outline);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final look = _presentation(scheme);

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: ExpansionTile(
        leading: Icon(look.icon, color: look.colour),
        title: Text(entry.paper,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(
          entry.isVerdict
              ? '${look.label} · ${entry.scoreLabel}'
              : look.label,
          style: TextStyle(color: look.colour),
        ),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (!entry.isVerdict)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 8),
                    child: Text(
                      'This is not a judgement on the paper. The confidence '
                      'model could not be reached, so the paper has been kept '
                      'and can be scored again.',
                      style: TextStyle(fontStyle: FontStyle.italic),
                    ),
                  ),
                for (final reason in entry.reasons)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text('• $reason'),
                  ),
                if (entry.at != null)
                  Text('Submitted ${entry.at}',
                      style: Theme.of(context).textTheme.bodySmall),
                Text(
                  entry.isStored
                      ? 'Kept on the server'
                      : 'Not kept — the file was discarded',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
