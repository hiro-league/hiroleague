import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:just_audio/just_audio.dart';

import '../../../../application/audio/active_audio_notifier.dart';
import '../../../../core/ui/theme/app_text_styles.dart';
import '../../../../core/utils/message_formatters.dart';
import '../../../../domain/models/message/audio_attachment.dart';
import '../../../../domain/models/message/message.dart';
import '../../../../domain/models/message/message_status.dart';
import 'delivery_indicator.dart';

/// Unified audio message bubble used for both user voice recordings
/// (with optional expandable transcript) and bot voiced text replies
/// (with optional expandable message text). One widget, parameterized.
class AudioMessageBubble extends ConsumerStatefulWidget {
  const AudioMessageBubble({
    super.key,
    required this.message,
    required this.audio,
    this.expandableText,
    this.expandableLabel = '',
  });

  final Message message;
  final AudioAttachment audio;
  final String? expandableText;
  final String expandableLabel;

  @override
  ConsumerState<AudioMessageBubble> createState() =>
      _AudioMessageBubbleState();
}

class _AudioMessageBubbleState extends ConsumerState<AudioMessageBubble>
    with WidgetsBindingObserver {
  /// Cached in [initState]: [ref] must not be used in [dispose] (element already unmounted).
  late final ActiveAudioController _activeAudio;

  late final AudioPlayer _player;
  bool _isPlaying = false;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  double _speed = 1.0;
  bool _sectionExpanded = false;

  static const _speeds = [0.5, 1.0, 1.5, 2.0];

  @override
  void initState() {
    super.initState();
    _activeAudio = ref.read(activeAudioProvider);
    WidgetsBinding.instance.addObserver(this);
    _player = AudioPlayer();
    _initPlayer();
  }

  Future<void> _initPlayer() async {
    final path = widget.audio.localPath;
    if (path == null || path.isEmpty) return;

    try {
      if (path.startsWith('http') ||
          path.startsWith('blob:') ||
          path.startsWith('data:')) {
        await _player.setUrl(path);
      } else {
        await _player.setFilePath(path);
      }
      final dur = _player.duration;
      if (dur != null) setState(() => _duration = dur);
    } catch (_) {
      // Audio source not yet available — player stays idle.
    }

    _player.durationStream.listen((d) {
      if (d != null && mounted) setState(() => _duration = d);
    });
    _player.positionStream.listen((p) {
      if (mounted) setState(() => _position = p);
    });
    _player.playerStateStream.listen((state) {
      if (!mounted) return;
      setState(() => _isPlaying = state.playing);
      if (state.processingState == ProcessingState.completed) {
        _player.stop();
        _player.seek(Duration.zero);
        setState(() {
          _isPlaying = false;
          _position = Duration.zero;
        });
      }
    });
  }

  @override
  void didUpdateWidget(AudioMessageBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.audio.localPath != widget.audio.localPath &&
        widget.audio.localPath != null) {
      _initPlayer();
    }
  }

  Future<void> _togglePlay() async {
    if (_isPlaying) {
      await _player.pause();
    } else {
      _activeAudio.claim(_player);
      await _player.play();
    }
  }

  void _cycleSpeed() {
    final idx = _speeds.indexOf(_speed);
    final next = _speeds[(idx + 1) % _speeds.length];
    setState(() => _speed = next);
    _player.setSpeed(next);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.inactive) {
      if (_isPlaying) _player.pause();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _activeAudio.release(_player);
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final isOut = widget.message.isOutbound;

    final bubbleColor = isOut ? cs.primary : cs.surfaceContainerHigh;
    final contentColor = isOut ? cs.onPrimary : cs.onSurface;
    final metaColor =
        isOut ? cs.onPrimary.withValues(alpha: 0.7) : cs.onSurfaceVariant;
    final sliderActiveColor = isOut ? cs.onPrimary : cs.primary;
    final sliderInactiveColor =
        isOut ? cs.onPrimary.withValues(alpha: 0.3) : cs.outlineVariant;

    final remaining =
        _duration > _position ? _duration - _position : Duration.zero;
    final durationLabel = _isPlaying
        ? MessageFormatters.formatDuration(remaining)
        : MessageFormatters.formatDuration(_duration > Duration.zero
            ? _duration
            : Duration(milliseconds: widget.audio.durationMs));

    final expandText = widget.expandableText;
    final showExpandable =
        expandText != null && expandText.isNotEmpty;

    return Align(
      alignment: isOut ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.75,
          minWidth: 200,
        ),
        child: Container(
          margin: EdgeInsets.only(
            left: isOut ? 56 : 8,
            right: isOut ? 8 : 56,
            top: 2,
            bottom: 2,
          ),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: bubbleColor,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(18),
              topRight: const Radius.circular(18),
              bottomLeft: Radius.circular(isOut ? 18 : 4),
              bottomRight: Radius.circular(isOut ? 4 : 18),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (!isOut) ...[
                Text(
                  MessageFormatters.shortDeviceId(widget.message.senderId),
                  style: AppTextStyles.messageTimestamp.copyWith(
                    color: cs.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
              ],
              _PlayerRow(
                isPlaying: _isPlaying,
                hasSource: widget.audio.isPlayable,
                contentColor: contentColor,
                sliderActiveColor: sliderActiveColor,
                sliderInactiveColor: sliderInactiveColor,
                position: _position,
                duration: _duration,
                speed: _speed,
                metaColor: metaColor,
                onTogglePlay: _togglePlay,
                onSeek: (v) =>
                    _player.seek(Duration(milliseconds: v.toInt())),
                onCycleSpeed: _cycleSpeed,
              ),
              _MetaRow(
                durationLabel: durationLabel,
                metaColor: metaColor,
                timestamp: widget.message.timestamp,
                isOutbound: isOut,
                status: widget.message.status,
              ),
              if (showExpandable)
                _ExpandableSection(
                  text: expandText,
                  label: widget.expandableLabel,
                  isExpanded: _sectionExpanded,
                  metaColor: metaColor,
                  contentColor: contentColor,
                  onToggle: () =>
                      setState(() => _sectionExpanded = !_sectionExpanded),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _PlayerRow extends StatelessWidget {
  const _PlayerRow({
    required this.isPlaying,
    required this.hasSource,
    required this.contentColor,
    required this.sliderActiveColor,
    required this.sliderInactiveColor,
    required this.position,
    required this.duration,
    required this.speed,
    required this.metaColor,
    required this.onTogglePlay,
    required this.onSeek,
    required this.onCycleSpeed,
  });

  final bool isPlaying;
  final bool hasSource;
  final Color contentColor;
  final Color sliderActiveColor;
  final Color sliderInactiveColor;
  final Duration position;
  final Duration duration;
  final double speed;
  final Color metaColor;
  final VoidCallback onTogglePlay;
  final ValueChanged<double> onSeek;
  final VoidCallback onCycleSpeed;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 36,
          height: 36,
          child: IconButton(
            padding: EdgeInsets.zero,
            icon: Icon(
              isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
              color: contentColor,
              size: 26,
            ),
            onPressed: hasSource ? onTogglePlay : null,
          ),
        ),
        const SizedBox(width: 4),
        Expanded(
          child: SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: 3,
              thumbShape:
                  const RoundSliderThumbShape(enabledThumbRadius: 5),
              overlayShape:
                  const RoundSliderOverlayShape(overlayRadius: 12),
              activeTrackColor: sliderActiveColor,
              inactiveTrackColor: sliderInactiveColor,
              thumbColor: sliderActiveColor,
              overlayColor: sliderActiveColor.withValues(alpha: 0.2),
            ),
            child: Slider(
              min: 0,
              max: duration.inMilliseconds.toDouble().clamp(1, double.infinity),
              value: position.inMilliseconds
                  .toDouble()
                  .clamp(0, duration.inMilliseconds.toDouble()),
              onChanged: duration > Duration.zero ? onSeek : null,
            ),
          ),
        ),
        const SizedBox(width: 4),
        GestureDetector(
          onTap: onCycleSpeed,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
            decoration: BoxDecoration(
              border: Border.all(
                color: contentColor.withValues(alpha: 0.35),
              ),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              '${speed == speed.truncateToDouble() ? speed.toStringAsFixed(0) : speed}x',
              style: AppTextStyles.messageTimestamp
                  .copyWith(color: metaColor, fontSize: 10),
            ),
          ),
        ),
      ],
    );
  }
}

class _MetaRow extends StatelessWidget {
  const _MetaRow({
    required this.durationLabel,
    required this.metaColor,
    required this.timestamp,
    required this.isOutbound,
    required this.status,
  });

  final String durationLabel;
  final Color metaColor;
  final DateTime timestamp;
  final bool isOutbound;
  final MessageStatus status;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, right: 2),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            durationLabel,
            style: AppTextStyles.messageTimestamp.copyWith(color: metaColor),
          ),
          const Spacer(),
          Text(
            MessageFormatters.formatTime(timestamp),
            style:
                AppTextStyles.messageTimestamp.copyWith(color: metaColor),
          ),
          if (isOutbound) ...[
            const SizedBox(width: 3),
            DeliveryIndicator(
              status: status,
              readColor: isOutbound ? Colors.white : null,
              defaultColor: isOutbound
                  ? Colors.white.withValues(alpha: 0.6)
                  : null,
            ),
          ],
        ],
      ),
    );
  }
}

/// Generic expandable text section — used for both transcript (on audio
/// messages) and message body (on voiced text messages).
class _ExpandableSection extends StatelessWidget {
  const _ExpandableSection({
    required this.text,
    required this.label,
    required this.isExpanded,
    required this.metaColor,
    required this.contentColor,
    required this.onToggle,
  });

  final String text;
  final String label;
  final bool isExpanded;
  final Color metaColor;
  final Color contentColor;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox(height: 4),
        GestureDetector(
          onTap: onToggle,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                isExpanded
                    ? Icons.expand_less_rounded
                    : Icons.expand_more_rounded,
                size: 16,
                color: metaColor,
              ),
              const SizedBox(width: 2),
              Text(
                label,
                style: AppTextStyles.messageTimestamp.copyWith(
                  color: metaColor,
                  decoration: TextDecoration.underline,
                ),
              ),
            ],
          ),
        ),
        AnimatedCrossFade(
          duration: const Duration(milliseconds: 180),
          crossFadeState: isExpanded
              ? CrossFadeState.showFirst
              : CrossFadeState.showSecond,
          firstChild: Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              text,
              style: AppTextStyles.messageBody
                  .copyWith(color: contentColor.withValues(alpha: 0.85)),
            ),
          ),
          secondChild: const SizedBox.shrink(),
        ),
      ],
    );
  }
}
