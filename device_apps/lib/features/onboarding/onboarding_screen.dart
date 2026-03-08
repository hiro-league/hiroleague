import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/auth/auth_notifier.dart';
import '../../application/auth/auth_state.dart';
import '../../core/constants/app_strings.dart';
import 'widgets/gateway_url_field.dart';
import 'widgets/pairing_code_form.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _formKey = GlobalKey<FormState>();
  final _gatewayUrlController = TextEditingController();
  final _pairingCodeController = TextEditingController();

  @override
  void dispose() {
    _gatewayUrlController.dispose();
    _pairingCodeController.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    await ref.read(authNotifierProvider.notifier).pair(
          _gatewayUrlController.text.trim(),
          _pairingCodeController.text.trim(),
        );
  }

  @override
  Widget build(BuildContext context) {
    final authAsync = ref.watch(authNotifierProvider);
    final isPairing = authAsync.valueOrNull is AuthPairing;
    final errorMsg = authAsync.valueOrNull is AuthError
        ? (authAsync.valueOrNull! as AuthError).message
        : null;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 48),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const _PhbBranding(),
                  const SizedBox(height: 40),
                  Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        GatewayUrlField(
                          controller: _gatewayUrlController,
                          enabled: !isPairing,
                        ),
                        const SizedBox(height: 16),
                        PairingCodeField(
                          controller: _pairingCodeController,
                          enabled: !isPairing,
                        ),
                      ],
                    ),
                  ),
                  if (errorMsg != null) ...[
                    const SizedBox(height: 16),
                    _ErrorBanner(message: errorMsg),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: isPairing ? null : _connect,
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                    ),
                    child: isPairing
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                              strokeWidth: 2.5,
                              color: Colors.white,
                            ),
                          )
                        : const Text('Connect'),
                  ),
                  const SizedBox(height: 16),
                  _QrScanButton(enabled: !isPairing),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PhbBranding extends StatelessWidget {
  const _PhbBranding();

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      children: [
        Container(
          width: 80,
          height: 80,
          decoration: BoxDecoration(
            color: cs.primaryContainer,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Icon(Icons.home_rounded, size: 44, color: cs.primary),
        ),
        const SizedBox(height: 20),
        Text(
          AppStrings.appName,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: cs.primary,
                fontWeight: FontWeight.w700,
              ),
        ),
        const SizedBox(height: 8),
        Text(
          'Connect to your gateway to get started',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: cs.onSurfaceVariant,
              ),
        ),
      ],
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: cs.errorContainer,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline_rounded, color: cs.onErrorContainer, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: cs.onErrorContainer),
            ),
          ),
        ],
      ),
    );
  }
}

class _QrScanButton extends StatelessWidget {
  const _QrScanButton({required this.enabled});

  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: enabled
          ? () => ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('QR scanning coming in a future update'),
                  behavior: SnackBarBehavior.floating,
                ),
              )
          : null,
      icon: const Icon(Icons.qr_code_scanner_rounded),
      label: const Text('Scan QR Code'),
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(48),
      ),
    );
  }
}
