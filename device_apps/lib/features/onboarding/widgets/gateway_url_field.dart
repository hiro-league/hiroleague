import 'package:flutter/material.dart';

class GatewayUrlField extends StatelessWidget {
  const GatewayUrlField({
    super.key,
    required this.controller,
    this.enabled = true,
  });

  final TextEditingController controller;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      enabled: enabled,
      keyboardType: TextInputType.url,
      autocorrect: false,
      decoration: const InputDecoration(
        labelText: 'Gateway URL',
        hintText: 'ws://192.168.1.x:8765',
        prefixIcon: Icon(Icons.link_rounded),
        border: OutlineInputBorder(),
      ),
      validator: (value) {
        final v = value?.trim() ?? '';
        if (v.isEmpty) return 'Gateway URL is required';
        if (!v.startsWith('ws://') && !v.startsWith('wss://')) {
          return 'Must start with ws:// or wss://';
        }
        return null;
      },
      autovalidateMode: AutovalidateMode.onUserInteraction,
    );
  }
}
