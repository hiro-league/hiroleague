import 'package:flutter/material.dart';

class PairingCodeField extends StatelessWidget {
  const PairingCodeField({
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
      keyboardType: TextInputType.text,
      autocorrect: false,
      decoration: const InputDecoration(
        labelText: 'Pairing Code',
        hintText: 'Enter the code shown on your desktop',
        prefixIcon: Icon(Icons.key_rounded),
        border: OutlineInputBorder(),
      ),
      validator: (value) {
        final v = value?.trim() ?? '';
        if (v.isEmpty) return 'Pairing code is required';
        if (v.length < 4) return 'Pairing code must be at least 4 characters';
        return null;
      },
      autovalidateMode: AutovalidateMode.onUserInteraction,
    );
  }
}
