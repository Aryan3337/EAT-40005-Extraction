import 'package:flutter/material.dart';

import '../../models/admin_audit.dart';
import '../../services/admin_service.dart';
import 'admin_audit_page.dart';

// Landing page of the admin area: a grid of feature tiles. Each tile opens its
// own screen, and the live counts are best-effort -- a failed request leaves
// the tile without a badge rather than blocking the dashboard.
class AdminDashboardPage extends StatefulWidget {
  const AdminDashboardPage({
    super.key,
    required this.service,
    required this.onOpenPapers,
    required this.onOpenFeedback,
    required this.onOpenUsers,
    required this.onOpenAudit,
    required this.onOpenChat,
    required this.onSignOut,
    this.adminEmail,
  });

  final AdminService service;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenPapers;
  final VoidCallback onOpenFeedback;
  final VoidCallback onOpenUsers;
  final VoidCallback onOpenAudit;
  final VoidCallback onSignOut;
  final String? adminEmail;

  @override
  State<AdminDashboardPage> createState() => _AdminDashboardPageState();
}

class _AdminDashboardPageState extends State<AdminDashboardPage> {
  int? _pendingFeedback;
  int? _totalFeedback;
  int? _userCount;
  AdminOverview? _overview;

  @override
  void initState() {
    super.initState();
    _loadCounts();
  }

  Future<void> _loadCounts() async {
    try {
      final stats = await widget.service.fetchFeedbackStats();
      if (!mounted) return;
      setState(() {
        _pendingFeedback = stats.pending;
        _totalFeedback = stats.total;
      });
    } catch (_) {}
    try {
      final overview = await widget.service.fetchOverview();
      if (!mounted) return;
      setState(() => _overview = overview);
    } catch (_) {}
    try {
      final users = await widget.service.fetchUsers();
      if (!mounted) return;
      setState(() => _userCount = users.length);
    } catch (_) {}
  }

  // Where the triples came from, how the papers fared, and what went wrong
  // recently -- each part only renders when there is something to show.
  List<Widget> _insights(AdminOverview overview) {
    const heading = TextStyle(
      fontSize: 16,
      fontWeight: FontWeight.w700,
      color: Color(0xFF172B4D),
    );
    return [
      if (overview.sources.isNotEmpty) ...[
        const SizedBox(height: 24),
        const Text('Triples by source paper', style: heading),
        const SizedBox(height: 8),
        for (final source in overview.sources.take(8))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(
              children: [
                Expanded(
                  child: Text(source.source, overflow: TextOverflow.ellipsis),
                ),
                Text('${source.triples}'),
              ],
            ),
          ),
      ],
      if (overview.papers.isNotEmpty) ...[
        const SizedBox(height: 24),
        const Text('Paper decisions', style: heading),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final entry in overview.papers.entries)
              Chip(label: Text('${entry.key}: ${entry.value}')),
          ],
        ),
      ],
      const SizedBox(height: 24),
      const Text('Recent errors and failures', style: heading),
      const SizedBox(height: 4),
      if (overview.recentErrors.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 8),
          child: Text('None recorded.'),
        )
      else
        for (final event in overview.recentErrors.take(5))
          AuditEventTile(event: event),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final tiles = [
      _DashboardTile(
        title: 'Chatbot',
        description:
            'Ask the Mandi/Garo knowledge assistant questions and '
            'review your chat history.',
        icon: Icons.forum_rounded,
        color: const Color(0xFF172B4D),
        onTap: widget.onOpenChat,
      ),
      _DashboardTile(
        title: 'Paper admission',
        description:
            'Upload research papers, score them and approve or '
            'reject them for extraction.',
        icon: Icons.upload_file_rounded,
        color: const Color(0xFF0D6EFD),
        onTap: widget.onOpenPapers,
      ),
      _DashboardTile(
        title: 'Feedback review',
        description:
            'Review user feedback and archive incorrect graph '
            'triples.',
        icon: Icons.fact_check_rounded,
        color: const Color(0xFF0F766E),
        badge: _pendingFeedback != null && _pendingFeedback! > 0
            ? '$_pendingFeedback pending'
            : null,
        onTap: widget.onOpenFeedback,
      ),
      _DashboardTile(
        title: 'Audit log',
        description:
            'See logins, paper decisions, reviews and failed actions, '
            'and who made each one.',
        icon: Icons.history_rounded,
        color: const Color(0xFFB7791F),
        badge: (_overview?.recentErrors.length ?? 0) > 0
            ? '${_overview!.recentErrors.length} recent errors'
            : null,
        onTap: widget.onOpenAudit,
      ),
      _DashboardTile(
        title: 'Manage users',
        description: 'Edit roles, reset passwords and remove accounts.',
        icon: Icons.people_alt_rounded,
        color: const Color(0xFF6F42C1),
        onTap: widget.onOpenUsers,
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin dashboard'),
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh counts',
            onPressed: _loadCounts,
          ),
          IconButton(
            icon: const Icon(Icons.logout_outlined),
            tooltip: 'Sign out',
            onPressed: widget.onSignOut,
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1100),
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              _WelcomeBanner(email: widget.adminEmail),
              const SizedBox(height: 20),
              Wrap(
                spacing: 16,
                runSpacing: 16,
                children: [
                  _StatCard(
                    label: 'Pending feedback',
                    value: _pendingFeedback,
                    icon: Icons.pending_actions_rounded,
                    color: const Color(0xFFB7791F),
                  ),
                  _StatCard(
                    label: 'Total feedback',
                    value: _totalFeedback,
                    icon: Icons.rate_review_rounded,
                    color: const Color(0xFF0F766E),
                  ),
                  _StatCard(
                    label: 'User accounts',
                    value: _userCount,
                    icon: Icons.groups_rounded,
                    color: const Color(0xFF6F42C1),
                  ),
                  _StatCard(
                    label: 'Triples in graph',
                    value: _overview?.relationships,
                    icon: Icons.hub_rounded,
                    color: const Color(0xFF0D6EFD),
                  ),
                  _StatCard(
                    label: 'Entities',
                    value: _overview?.nodes,
                    icon: Icons.circle_outlined,
                    color: const Color(0xFF172B4D),
                  ),
                  _StatCard(
                    label: 'Archived triples',
                    value: _overview?.archived,
                    icon: Icons.inventory_2_outlined,
                    color: const Color(0xFF6B778C),
                  ),
                ],
              ),
              if (_overview != null) ..._insights(_overview!),
              const SizedBox(height: 28),
              const Text(
                'Management tools',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF172B4D),
                ),
              ),
              const SizedBox(height: 12),
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = constraints.maxWidth >= 900
                      ? 3
                      : constraints.maxWidth >= 560
                      ? 2
                      : 1;
                  const gap = 16.0;
                  final width =
                      (constraints.maxWidth - gap * (columns - 1)) / columns;
                  return Wrap(
                    spacing: gap,
                    runSpacing: gap,
                    children: [
                      for (final tile in tiles)
                        SizedBox(width: width, child: tile),
                    ],
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WelcomeBanner extends StatelessWidget {
  const _WelcomeBanner({this.email});

  final String? email;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF172B4D), Color(0xFF0D6EFD)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.admin_panel_settings_rounded,
            color: Colors.white,
            size: 40,
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Administration',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  email == null
                      ? 'Manage papers, feedback and users.'
                      : 'Signed in as $email',
                  style: const TextStyle(color: Color(0xFFD6E4FF)),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });

  final String label;
  final int? value;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 240,
      child: Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              CircleAvatar(
                backgroundColor: color.withValues(alpha: 0.12),
                child: Icon(icon, color: color),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      value?.toString() ?? '—',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      label,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DashboardTile extends StatelessWidget {
  const _DashboardTile({
    required this.title,
    required this.description,
    required this.icon,
    required this.color,
    required this.onTap,
    this.badge,
  });

  final String title;
  final String description;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;
  final String? badge;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 48,
                    height: 48,
                    decoration: BoxDecoration(
                      color: color,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(icon, color: Colors.white),
                  ),
                  const Spacer(),
                  if (badge != null)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFFB42318),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        badge!,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 16),
              Text(
                title,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF172B4D),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                description,
                style: const TextStyle(color: Color(0xFF637078), height: 1.4),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Text(
                    'Open',
                    style: TextStyle(color: color, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(width: 4),
                  Icon(Icons.arrow_forward_rounded, size: 18, color: color),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
