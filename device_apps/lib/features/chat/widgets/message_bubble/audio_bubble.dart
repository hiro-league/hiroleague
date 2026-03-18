import 'package:flutter/material.dart';
import 'package:just_audio/just_audio.dart';

import '../../../../core/ui/theme/app_text_styles.dart';
import '../../../../domain/models/message/message.dart';
import '../../../../domain/models/message/message_content.dart';
import 'delivery_indicator.dart';

class AudioBubble extends StatefulWidget {
  const AudioBubble({
    super.key,
    required this.message,
    required this.content,
  });

  final Message message;
  final AudioContent content;

  @override
  State<AudioBubble> createState() => _AudioBubbleState();
}

class _AudioBubbleState extends State<AudioBubble> {
  late final AudioPlayer _player;
  bool _isPlaying = false;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  double _speed = 1.0;
  bool _transcriptExpanded = false;

  static const _speeds = [1.0, 1.5, 2.0];

  @override
  void initState() {
    super.initState();
    _player = AudioPlayer();
    _initPlayer();
  }

  Future<void> _initPlayer() async {
    final path = widget.content.localPath;
    if (path == null || path.isEmpty) return;

    try {
      if (path.startsWith('http') || path.startsWith('blob:') || path.startsWith('data:')) {
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
        _player.seek(Duration.zero);
        setState(() {
          _isPlaying = false;
          _position = Duration.zero;
        });
      }
    });
  }

  @override
  void didUpdateWidget(AudioBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    // If local path became available (inbound message saved), reload.
    if (oldWidget.content.localPath != widget.content.localPath &&
        widget.content.localPath != null) {
      _initPlayer();
    }
  }

  Future<void> _togglePlay() async {
    if (_isPlaying) {
      await _player.pause();
    } else {
      await _player.play();
    }
  }

  void _cycleSpeed() {
    final idx = _speeds.indexOf(_speed);
    final next = _speeds[(idx + 1) % _speeds.length];
    setState(() => _speed = next);
    _player.setSpeed(next);
  }

  String _formatDuration(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  void dispose() {
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

    final remaining = _duration > _position ? _duration - _position : Duration.zero;
    final durationLabel = _isPlaying
        ? _formatDuration(remaining)
        : _formatDuration(_duration > Duration.zero
            ? _duration
            : Duration(milliseconds: widget.content.durationMs));

    final hasTranscript = widget.content.transcript != null &&
        widget.content.transcript!.isNotEmpty;

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
                  _shortId(widget.message.senderId),
                  style: AppTextStyles.messageTimestamp.copyWith(
                    color: cs.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
              ],

              // Player row
              Row(
                children: [
                  // Play/pause button
                  SizedBox(
                    width: 36,
                    height: 36,
                    child: IconButton(
                      padding: EdgeInsets.zero,
                      icon: Icon(
                        _isPlaying
                            ? Icons.pause_rounded
                            : Icons.play_arrow_rounded,
                        color: contentColor,
                        size: 26,
                      ),
                      onPressed: widget.content.localPath != null
                          ? _togglePlay
                          : null,
                    ),
                  ),
                  const SizedBox(width: 4),

                  // Seek bar
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
                        overlayColor:
                            sliderActiveColor.withValues(alpha: 0.2),
                      ),
                      child: Slider(
                        min: 0,
                        max: _duration.inMilliseconds.toDouble().clamp(1, double.infinity),
                        value: _position.inMilliseconds
                            .toDouble()
                            .clamp(0, _duration.inMilliseconds.toDouble()),
                        onChanged: _duration > Duration.zero
                            ? (v) => _player.seek(
                                Duration(milliseconds: v.toInt()))
                            : null,
                      ),
                    ),
                  ),
                ],
              ),

              // Meta row: duration + speed + timestamp + delivery
              Padding(
                padding: const EdgeInsets.only(left: 4, right: 2),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      durationLabel,
                      style: AppTextStyles.messageTimestamp
                          .copyWith(color: metaColor),
                    ),
                    const SizedBox(width: 8),
                    // Speed chip
                    GestureDetector(
                      onTap: _cycleSpeed,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 5, vertical: 1),
                        decoration: BoxDecoration(
                          border: Border.all(
                            color: contentColor.withValues(alpha: 0.35),
                          ),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          '${_speed == _speed.truncateToDouble() ? _speed.toStringAsFixed(0) : _speed}x',
                          style: AppTextStyles.messageTimestamp
                              .copyWith(color: metaColor, fontSize: 10),
                        ),
                      ),
                    ),
                    const Spacer(),
                    Text(
                      _formatTime(widget.message.timestamp),
                      style: AppTextStyles.messageTimestamp
                          .copyWith(color: metaColor),
                    ),
                    if (widget.message.isOutbound) ...[
                      const SizedBox(width: 3),
                      DeliveryIndicator(
                        status: widget.message.status,
                        readColor: isOut ? Colors.white : null,
                        defaultColor: isOut
                            ? Colors.white.withValues(alpha: 0.6)
                            : null,
                      ),
                    ],
                  ],
                ),
              ),

              // Expandable transcript
              if (hasTranscript) ...[
                const SizedBox(height: 4),
                GestureDetector(
                  onTap: () =>
                      setState(() => _transcriptExpanded = !_transcriptExpanded),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        _transcriptExpanded
                            ? Icons.expand_less_rounded
                            : Icons.expand_more_rounded,
                        size: 16,
                        color: metaColor,
                      ),
                      const SizedBox(width: 2),
                      Text(
                        'Transcript',
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
                  crossFadeState: _transcriptExpanded
                      ? CrossFadeState.showFirst
                      : CrossFadeState.showSecond,
                  firstChild: Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      widget.content.transcript!,
                      style: AppTextStyles.messageBody
                          .copyWith(color: contentColor.withValues(alpha: 0.85)),
                    ),
                  ),
                  secondChild: const SizedBox.shrink(),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  String _shortId(String id) {
    if (id.length <= 8) return id;
    return '…${id.substring(id.length - 8)}';
  }

  String _formatTime(DateTime dt) {
    final local = dt.toLocal();
    final h = local.hour.toString().padLeft(2, '0');
    final m = local.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }
}
