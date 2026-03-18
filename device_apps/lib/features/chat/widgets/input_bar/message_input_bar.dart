import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';

import '../../../../application/providers.dart';
import '../../../../core/errors/app_exception.dart';
import '../../../../domain/services/audio_recording_service.dart';

/// Recording state machine for the input bar.
enum _RecordingState { idle, recording, cancelling }

class MessageInputBar extends ConsumerStatefulWidget {
  const MessageInputBar({super.key, required this.channelId});

  final String channelId;

  @override
  ConsumerState<MessageInputBar> createState() => _MessageInputBarState();
}

class _MessageInputBarState extends ConsumerState<MessageInputBar>
    with SingleTickerProviderStateMixin {
  final _controller = TextEditingController();
  final _recording = AudioRecordingService();

  bool _hasText = false;
  _RecordingState _state = _RecordingState.idle;
  int _elapsedSeconds = 0;
  Timer? _timer;

  // On web, microphone permission must be granted before the long-press gesture
  // can start recording. This flag tracks whether we've already confirmed access.
  bool _micPermissionGranted = false;

  // Pulse animation for the mic button while recording.
  late AnimationController _pulseCtrl;
  late Animation<double> _pulseAnim;

  // Tracks horizontal drag offset to detect slide-to-cancel.
  double _dragStartX = 0;
  bool _wasCancelled = false;

  static const double _cancelThreshold = -80.0; // px to the left

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final has = _controller.text.trim().isNotEmpty;
      if (has != _hasText) setState(() => _hasText = has);
    });

    // On mobile, permission is already managed by the OS dialog flow.
    // On web, check if the browser has previously granted access so we skip
    // the tap-to-unlock badge for users who already allowed the microphone.
    if (kIsWeb) {
      _checkWebPermissionSilently();
    } else {
      _micPermissionGranted = true; // mobile handles this in startRecording()
    }

    _pulseCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    )..repeat(reverse: true);
    _pulseAnim = Tween<double>(begin: 1.0, end: 1.35).animate(
      CurvedAnimation(parent: _pulseCtrl, curve: Curves.easeInOut),
    );
    _pulseCtrl.stop();
  }

  // -------------------------------------------------------------------------
  // Text send
  // -------------------------------------------------------------------------

  Future<void> _sendText() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    _controller.clear();
    try {
      await ref.read(messageSendProvider.notifier).sendText(
            channelId: widget.channelId,
            text: text,
          );
    } on AppException catch (e) {
      _showError('Failed to send: ${e.message}');
    } catch (_) {
      _showError('Failed to send message');
    }
  }

  // -------------------------------------------------------------------------
  // Recording lifecycle
  // -------------------------------------------------------------------------

  /// Silently checks if microphone permission is already granted on web.
  /// Does NOT trigger a browser prompt — only reads the existing state.
  Future<void> _checkWebPermissionSilently() async {
    try {
      final recorder = AudioRecorder();
      final granted = await recorder.hasPermission();
      await recorder.dispose();
      if (granted && mounted) setState(() => _micPermissionGranted = true);
    } catch (_) {
      // Permission API not available or blocked — ignore, user will tap to grant.
    }
  }

  /// On web the browser permission dialog blocks the long-press gesture.
  /// We request permission on the first *tap* of the mic button so it is
  /// granted before the user tries to hold. On mobile, permission is checked
  /// inside [AudioRecordingService.startRecording] with a clear system dialog.
  Future<void> _ensureWebPermission() async {
    if (!kIsWeb || _micPermissionGranted) return;
    try {
      final recorder = AudioRecorder();
      final granted = await recorder.hasPermission();
      await recorder.dispose();
      if (granted) {
        setState(() => _micPermissionGranted = true);
      } else {
        _showError('Microphone access is required. Please allow it in your browser and try again.');
      }
    } catch (_) {
      _showError('Could not request microphone permission.');
    }
  }

  void _onLongPressStart(LongPressStartDetails details) {
    if (_state != _RecordingState.idle) return;
    // On web, block the gesture until permission is confirmed.
    if (kIsWeb && !_micPermissionGranted) {
      _ensureWebPermission();
      return;
    }
    _dragStartX = details.globalPosition.dx;
    _wasCancelled = false;
    _startRecording();
  }

  void _onLongPressMoveUpdate(LongPressMoveUpdateDetails details) {
    if (_state != _RecordingState.recording) return;
    final delta = details.globalPosition.dx - _dragStartX;
    if (delta < _cancelThreshold) {
      _cancelRecording();
    }
  }

  void _onLongPressEnd(LongPressEndDetails details) {
    if (_state == _RecordingState.recording) {
      _stopAndSend();
    }
  }

  Future<void> _startRecording() async {
    try {
      await _recording.startRecording();
    } catch (e) {
      _showError('Could not start recording: $e');
      return;
    }
    setState(() {
      _state = _RecordingState.recording;
      _elapsedSeconds = 0;
    });
    _pulseCtrl.repeat(reverse: true);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      final elapsed = _recording.elapsedMs ~/ 1000;
      setState(() => _elapsedSeconds = elapsed);
      if (elapsed >= 60) _stopAndSend();
    });

    // Listen for auto-stop (from the service's 60-second timer).
    _recording.isRecording.addListener(_onRecordingStateChanged);
  }

  void _onRecordingStateChanged() {
    if (!_recording.isRecording.value && _state == _RecordingState.recording) {
      _stopAndSend();
    }
  }

  Future<void> _stopAndSend() async {
    if (_state != _RecordingState.recording) return;
    _cleanupTimer();
    setState(() => _state = _RecordingState.idle);

    final result = await _recording.stopRecording();
    if (result == null || result.durationMs < 200 || _wasCancelled) return;

    try {
      await ref.read(messageSendProvider.notifier).sendAudio(
            channelId: widget.channelId,
            recordingResult: result,
          );
    } on AppException catch (e) {
      _showError('Failed to send audio: ${e.message}');
    } catch (_) {
      _showError('Failed to send audio');
    }
  }

  Future<void> _cancelRecording() async {
    if (_state != _RecordingState.recording) return;
    _wasCancelled = true;
    _cleanupTimer();
    setState(() => _state = _RecordingState.cancelling);
    await _recording.cancelRecording();
    if (mounted) setState(() => _state = _RecordingState.idle);
  }

  void _cleanupTimer() {
    _timer?.cancel();
    _timer = null;
    _pulseCtrl.stop();
    _pulseCtrl.reset();
    _recording.isRecording.removeListener(_onRecordingStateChanged);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  String _formatElapsed(int seconds) {
    final m = (seconds ~/ 60).toString().padLeft(2, '0');
    final s = (seconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final gatewayState = ref.watch(gatewayProvider);
    final isConnected = gatewayState is GatewayConnected;

    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
        decoration: BoxDecoration(
          color: cs.surface,
          border: Border(
            top: BorderSide(color: cs.outlineVariant, width: 0.5),
          ),
        ),
        child: _state == _RecordingState.recording
            ? _buildRecordingOverlay(cs, isConnected)
            : _buildIdleBar(cs, isConnected),
      ),
    );
  }

  Widget _buildIdleBar(ColorScheme cs, bool isConnected) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: TextField(
            controller: _controller,
            enabled: isConnected,
            maxLines: 5,
            minLines: 1,
            textInputAction: TextInputAction.newline,
            keyboardType: TextInputType.multiline,
            decoration: InputDecoration(
              hintText: isConnected ? 'Type a message…' : 'Connecting to gateway…',
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(24),
                borderSide: BorderSide.none,
              ),
              filled: true,
              fillColor: cs.surfaceContainerHigh,
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              isDense: true,
            ),
          ),
        ),
        const SizedBox(width: 8),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 150),
          transitionBuilder: (child, anim) =>
              ScaleTransition(scale: anim, child: child),
          child: _hasText
              ? AnimatedOpacity(
                  key: const ValueKey('send'),
                  opacity: isConnected ? 1.0 : 0.5,
                  duration: const Duration(milliseconds: 150),
                  child: IconButton.filled(
                    onPressed: (isConnected && _hasText) ? _sendText : null,
                    icon: const Icon(Icons.send_rounded),
                    style: IconButton.styleFrom(
                      backgroundColor: cs.primary,
                      foregroundColor: cs.onPrimary,
                    ),
                  ),
                )
              : GestureDetector(
                  key: const ValueKey('mic'),
                  // On web, a plain tap requests mic permission the first time.
                  onTap: (kIsWeb && isConnected && !_micPermissionGranted)
                      ? _ensureWebPermission
                      : null,
                  onLongPressStart:
                      isConnected ? _onLongPressStart : null,
                  onLongPressMoveUpdate:
                      isConnected ? _onLongPressMoveUpdate : null,
                  onLongPressEnd:
                      isConnected ? _onLongPressEnd : null,
                  child: AnimatedOpacity(
                    opacity: isConnected ? 1.0 : 0.5,
                    duration: const Duration(milliseconds: 150),
                    child: Container(
                      width: 48,
                      height: 48,
                      decoration: BoxDecoration(
                        color: cs.primary,
                        shape: BoxShape.circle,
                      ),
                      // Show a small badge on web until permission is confirmed.
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          Icon(Icons.mic_rounded, color: cs.onPrimary),
                          if (kIsWeb && !_micPermissionGranted)
                            Positioned(
                              top: 8,
                              right: 8,
                              child: Container(
                                width: 8,
                                height: 8,
                                decoration: BoxDecoration(
                                  color: cs.error,
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
        ),
      ],
    );
  }

  Widget _buildRecordingOverlay(ColorScheme cs, bool isConnected) {
    return Row(
      children: [
        // Slide to cancel — left side
        Expanded(
          child: GestureDetector(
            onTap: _cancelRecording,
            child: Row(
              children: [
                Icon(
                  Icons.chevron_left_rounded,
                  color: cs.onSurfaceVariant,
                  size: 20,
                ),
                Text(
                  'Slide to cancel',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: cs.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
        ),

        // Timer
        Text(
          _formatElapsed(_elapsedSeconds),
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                fontFeatures: const [FontFeature.tabularFigures()],
                color: cs.onSurface,
              ),
        ),

        const SizedBox(width: 12),

        // Pulsing mic button
        GestureDetector(
          onLongPressEnd: _onLongPressEnd,
          onLongPressMoveUpdate: _onLongPressMoveUpdate,
          child: AnimatedBuilder(
            animation: _pulseAnim,
            builder: (context, child) {
              return Transform.scale(
                scale: _pulseAnim.value,
                child: child,
              );
            },
            child: Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: cs.error,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: cs.error.withValues(alpha: 0.4),
                    blurRadius: 10,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: Icon(Icons.mic_rounded, color: cs.onError),
            ),
          ),
        ),
      ],
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    _recording.dispose();
    _timer?.cancel();
    _pulseCtrl.dispose();
    super.dispose();
  }
}
