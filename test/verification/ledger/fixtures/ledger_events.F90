module ledger_events
  ! Structured event emission for the assumption-ledger fixture.
  ! Schemes and the driver print EV| lines; run_ledger.py parses them.
  ! Not a CCPP scheme: no metadata, compiled alongside the fixture.

  implicit none
  private

  public :: ev_call
  public :: ev_idx
  public :: ev_constmeta
  public :: ev_val
  public :: ev_host
  public :: ev_text

contains

  subroutine ev_call(scheme, phase, nstep)
    ! A scheme phase subroutine was entered.
    character(len=*), intent(in) :: scheme
    character(len=*), intent(in) :: phase
    integer,          intent(in) :: nstep

    write(6, '(5a,i0)') 'EV|call|', scheme, '|', phase, '|', nstep
  end subroutine ev_call

  subroutine ev_idx(side, stdname, index)
    ! A constituent index lookup result (side = host or scheme).
    character(len=*), intent(in) :: side
    character(len=*), intent(in) :: stdname
    integer,          intent(in) :: index

    write(6, '(5a,i0)') 'EV|idx|', side, '|', trim(stdname), '|', index
  end subroutine ev_idx

  subroutine ev_constmeta(index, stdname)
    ! The constituent standard name stored at a host-side index.
    integer,          intent(in) :: index
    character(len=*), intent(in) :: stdname

    write(6, '(a,i0,2a)') 'EV|constmeta|', index, '|', trim(stdname)
  end subroutine ev_constmeta

  subroutine ev_val(tag, name, value)
    ! A probed real value; es25.16e3 survives three-digit exponents.
    use ccpp_kinds, only: kind_phys
    character(len=*),     intent(in) :: tag
    character(len=*),     intent(in) :: name
    real(kind=kind_phys), intent(in) :: value

    write(6, '(5a,es25.16e3)') 'EV|val|', tag, '|', trim(name), '|', value
  end subroutine ev_val

  subroutine ev_host(stage, errflg, errmsg)
    ! Outcome of one host-cap call; the message is recorded for human
    ! debugging only - checks assert the code and message emptiness.
    character(len=*), intent(in) :: stage
    integer,          intent(in) :: errflg
    character(len=*), intent(in) :: errmsg

    if (len_trim(errmsg) > 0) then
      write(6, '(3a,i0,2a)') 'EV|host|', stage, '|', errflg, '|', &
           trim(errmsg)
    else
      write(6, '(3a,i0,a)') 'EV|host|', stage, '|', errflg, '|-'
    end if
  end subroutine ev_host

  subroutine ev_text(kind, text)
    ! Free-form single-field event (begin/end/parts).
    character(len=*), intent(in) :: kind
    character(len=*), intent(in) :: text

    write(6, '(4a)') 'EV|', kind, '|', trim(text)
  end subroutine ev_text

end module ledger_events
