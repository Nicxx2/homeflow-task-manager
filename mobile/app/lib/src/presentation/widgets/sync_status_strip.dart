import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../application/app_controller.dart';
import '../../core/models/task_cache_snapshot.dart';

class SyncStatusStrip extends StatelessWidget {
  const SyncStatusStrip({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final status = HeaderStatus.fromController(controller);
    final lastSuccessfulSync = controller.cacheSnapshot?.lastSuccessfulSyncAt;
    final updatedLabel = lastSuccessfulSync == null
        ? 'Updated never'
        : _formatUpdatedLabel(lastSuccessfulSync);

    return Row(
      children: [
        StatusPill(label: status.label, tone: status.tone),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            updatedLabel,
            textAlign: TextAlign.end,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }

  String _formatUpdatedLabel(DateTime value) {
    final local = value.toLocal();
    final now = DateTime.now();
    final isToday = now.year == local.year &&
        now.month == local.month &&
        now.day == local.day;
    return isToday
        ? 'Updated ${DateFormat('HH:mm').format(local)}'
        : 'Updated ${DateFormat('dd MMM, HH:mm').format(local)}';
  }
}

enum StatusTone { success, warning, danger, neutral }

class HeaderStatus {
  const HeaderStatus({required this.label, required this.tone});

  final String label;
  final StatusTone tone;

  factory HeaderStatus.fromController(AppController controller) {
    if (controller.isSyncing) {
      return const HeaderStatus(label: 'Syncing', tone: StatusTone.neutral);
    }
    if (controller.needsReauth) {
      return const HeaderStatus(label: 'Sign in', tone: StatusTone.danger);
    }

    final snapshot = controller.cacheSnapshot;
    if (snapshot == null) {
      if (controller.currentBaseUrl == null) {
        return const HeaderStatus(
          label: 'Setup needed',
          tone: StatusTone.neutral,
        );
      }
      return const HeaderStatus(label: 'No cache', tone: StatusTone.warning);
    }

    switch (snapshot.lastSyncResult) {
      case SyncResultStatus.success:
        if (controller.isDataStale) {
          return const HeaderStatus(label: 'Cached', tone: StatusTone.warning);
        }
        return const HeaderStatus(
          label: 'Connected',
          tone: StatusTone.success,
        );
      case SyncResultStatus.networkUnavailable:
      case SyncResultStatus.serverUnreachable:
        return const HeaderStatus(
          label: 'Offline mode',
          tone: StatusTone.warning,
        );
      case SyncResultStatus.authRequired:
        return const HeaderStatus(label: 'Sign in', tone: StatusTone.danger);
      case SyncResultStatus.serverError:
      case SyncResultStatus.validationError:
      case SyncResultStatus.unknownError:
        return const HeaderStatus(label: 'Sync issue', tone: StatusTone.danger);
      case SyncResultStatus.neverSynced:
        return const HeaderStatus(
          label: 'No sync yet',
          tone: StatusTone.warning,
        );
    }
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.tone});

  final String label;
  final StatusTone tone;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (background, foreground) = switch (tone) {
      StatusTone.success => (
          scheme.primaryContainer,
          scheme.onPrimaryContainer,
        ),
      StatusTone.warning => (
          scheme.tertiaryContainer,
          scheme.onTertiaryContainer,
        ),
      StatusTone.danger => (scheme.errorContainer, scheme.onErrorContainer),
      StatusTone.neutral => (
          scheme.surfaceContainerHighest,
          scheme.onSurface,
        ),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: foreground,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            label,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}
