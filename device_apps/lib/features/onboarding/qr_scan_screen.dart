import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/constants/app_strings.dart';

class QrScanScreen extends StatefulWidget {
  const QrScanScreen({super.key});

  /// Sentinel value popped when the user denied camera permission.
  /// The caller hides the QR button for the remainder of the session.
  static const String permissionDeniedMarker = '__qr_permission_denied__';

  @override
  State<QrScanScreen> createState() => _QrScanScreenState();
}

class _QrScanScreenState extends State<QrScanScreen> with WidgetsBindingObserver {
  final MobileScannerController _controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
  );

  StreamSubscription<Object?>? _subscription;
  bool _hasScanned = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _subscription = _controller.barcodes.listen(_handleBarcode);
    unawaited(_controller.start());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Permission dialogs can trigger lifecycle changes before the controller
    // is ready — guard against starting/stopping prematurely.
    if (!_controller.value.hasCameraPermission) return;

    switch (state) {
      case AppLifecycleState.detached:
      case AppLifecycleState.hidden:
      case AppLifecycleState.paused:
        return;
      case AppLifecycleState.resumed:
        _subscription = _controller.barcodes.listen(_handleBarcode);
        unawaited(_controller.start());
      case AppLifecycleState.inactive:
        unawaited(_subscription?.cancel());
        _subscription = null;
        unawaited(_controller.stop());
    }
  }

  void _handleBarcode(BarcodeCapture capture) {
    if (_hasScanned) return;
    final rawValue = capture.barcodes.firstOrNull?.rawValue;
    if (rawValue != null && mounted) {
      _hasScanned = true;
      context.pop(rawValue);
    }
  }

  @override
  Future<void> dispose() async {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_subscription?.cancel());
    _subscription = null;
    super.dispose();
    await _controller.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text(AppStrings.qrScanTitle)),
      body: MobileScanner(
        controller: _controller,
        // mobile_scanner 7.x errorBuilder takes 2 params — no child argument.
        errorBuilder: (context, error) => _ScanErrorView(
          error: error,
          onDismiss: () => context.pop(
            error.errorCode == MobileScannerErrorCode.permissionDenied
                ? QrScanScreen.permissionDeniedMarker
                : null,
          ),
        ),
      ),
    );
  }
}

class _ScanErrorView extends StatelessWidget {
  const _ScanErrorView({required this.error, required this.onDismiss});

  final MobileScannerException error;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final message = switch (error.errorCode) {
      MobileScannerErrorCode.permissionDenied =>
        'Camera permission was denied.\nYou can enable it in your device Settings.',
      MobileScannerErrorCode.unsupported =>
        'Camera scanning is not supported on this device.',
      _ => 'Could not start camera: ${error.errorDetails?.message ?? 'Unknown error'}',
    };

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.no_photography_rounded, size: 56, color: cs.error),
            const SizedBox(height: 16),
            Text(
              message,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: onDismiss,
              child: const Text(AppStrings.close),
            ),
          ],
        ),
      ),
    );
  }
}
