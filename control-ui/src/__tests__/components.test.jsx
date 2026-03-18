/**
 * Tests for UI components — Card, Button, StatusBadge, Modal.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Card, { StatCard } from '../components/Card'
import Button from '../components/Button'
import StatusBadge from '../components/StatusBadge'
import Modal from '../components/Modal'

describe('Card', () => {
  it('renders title and children', () => {
    render(<Card title="Test Card"><p>Card content</p></Card>)
    expect(screen.getByText('Test Card')).toBeInTheDocument()
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })

  it('renders without title', () => {
    render(<Card><p>No title</p></Card>)
    expect(screen.getByText('No title')).toBeInTheDocument()
  })

  it('renders actions in header', () => {
    render(<Card title="With Actions" actions={<button>Action</button>}><p>Body</p></Card>)
    expect(screen.getByText('Action')).toBeInTheDocument()
  })
})

describe('StatCard', () => {
  it('renders label and value', () => {
    render(<StatCard label="Sessions" value="42" />)
    expect(screen.getByText('Sessions')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('renders subtext when provided', () => {
    render(<StatCard label="Status" value="Running" subtext="since 10am" />)
    expect(screen.getByText('since 10am')).toBeInTheDocument()
  })
})

describe('Button', () => {
  it('renders with text and handles click', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Click Me</Button>)
    fireEvent.click(screen.getByText('Click Me'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('is disabled when disabled prop is true', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByText('Disabled')).toBeDisabled()
  })

  it('applies variant classes', () => {
    const { container } = render(<Button variant="danger">Delete</Button>)
    const btn = container.querySelector('button')
    expect(btn.className).toContain('ef4444')
  })
})

describe('StatusBadge', () => {
  it('renders status text', () => {
    render(<StatusBadge status="completed" />)
    expect(screen.getByText('completed')).toBeInTheDocument()
  })

  it('applies completed style', () => {
    const { container } = render(<StatusBadge status="completed" />)
    const badge = container.querySelector('span')
    expect(badge.className).toContain('22c55e')
  })

  it('applies failed style', () => {
    const { container } = render(<StatusBadge status="failed" />)
    const badge = container.querySelector('span')
    expect(badge.className).toContain('ef4444')
  })

  it('handles unknown status gracefully', () => {
    render(<StatusBadge status="unknown-thing" />)
    expect(screen.getByText('unknown-thing')).toBeInTheDocument()
  })
})

describe('Modal', () => {
  it('renders nothing when closed', () => {
    render(<Modal open={false} onClose={() => {}} title="Hidden"><p>Content</p></Modal>)
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument()
  })

  it('renders content when open', () => {
    render(<Modal open={true} onClose={() => {}} title="Visible"><p>Modal body</p></Modal>)
    expect(screen.getByText('Visible')).toBeInTheDocument()
    expect(screen.getByText('Modal body')).toBeInTheDocument()
  })

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn()
    render(<Modal open={true} onClose={onClose} title="Close Test"><p>Body</p></Modal>)
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose on Escape key', () => {
    const onClose = vi.fn()
    render(<Modal open={true} onClose={onClose} title="Escape Test"><p>Body</p></Modal>)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
