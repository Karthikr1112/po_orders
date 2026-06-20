from django import forms
from .models import PurchaseOrder, AdminBudget

class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ['vendor', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

class AdminBudgetForm(forms.ModelForm):
    class Meta:
        model = AdminBudget
        fields = ['approved_amount', 'notes']
        widgets = {
            'approved_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }
